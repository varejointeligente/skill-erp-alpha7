#!/usr/bin/env python3
"""
Opera o ERP Alpha 7 pelas facades EJB do servidor de aplicação (não pelo banco).

Executa o `alpha7-cli.jar` que mora ao lado deste arquivo: ele faz login no servidor do
Alpha 7, chama a operação pedida e imprime JSON — `{"result": ...}` (exit 0)
ou `{"error": ...}` (exit 1). É o caminho para ESCREVER no ERP passando pelas regras de
negócio, permissões e log dele, em vez de `INSERT`/`UPDATE` direto no PostgreSQL.

Uso:
    alpha7_cli.py --preparar
    alpha7_cli.py invoke GrupoConsumidores findAllDTOs
    alpha7_cli.py invoke GrupoConsumidores findGrupoConsumidoresFinderDTOs --stdin '{"args":["VIP",20,true]}'
    alpha7_cli.py cadastrar-grupo-consumidores --stdin '{"nome":"Clientes VIP"}' --confirmar-escrita
    alpha7_cli.py grupo-consumidores-add 123 --stdin '{"pessoas":[456,789]}' --confirmar-escrita

Opções deste script (o resto vai para o CLI):
    --perfil NOME          perfil de credenciais (padrão: A7_PERFIL ou "default")
    --stdin-file ARQ       payload do comando, lido de um arquivo JSON ("-" = stdin) — o jeito
                           que funciona igual em Windows, Linux e macOS
    --stdin JSON           payload direto no argumento (as aspas do JSON brigam com o cmd e o
                           PowerShell: no Windows prefira --stdin-file)
    --confirmar-escrita    obrigatório em todo comando que grava no ERP
    --preparar             só confere/prepara libs, Java e o CLI, sem chamar o ERP
    --servidores           lista os servidores cadastrados no A7Pharma desta máquina (os do
                           combo do login), sem chamar o ERP
    --baixar-libs          baixa as libs do servidor mesmo havendo A7Pharma instalado
    --timeout SEG          tempo máximo da chamada (padrão 300)

Credenciais: gravadas por `alpha7_credenciais.py` (janela que a pessoa preenche) em ~/.config/erp-alpha7/<perfil>.env
(no Windows, %APPDATA%/erp-alpha7/<perfil>.env). (Variáveis de ambiente de mesmo nome têm precedência.) Nada de credencial é impresso, e a
senha vai para o Java por variável de ambiente, nunca pela linha de comando.

    A7_APP_HOST  A7_APP_PORT (8443)  A7_APP_USER  A7_APP_PASS
    A7_EJB_USER  A7_EJB_PASS    conexão EJB (opcional: o CLI tem o padrão do cliente A7Pharma)
    A7_WS_USER   A7_WS_PASS     WS de atualização — só para baixar libs do servidor

Runtime (achado sozinho; as variáveis forçam):
    A7PHARMA_HOME   instalação do A7Pharma (libs + JRE 17 saem dela)
    A7_LIB          pasta com os jars do cliente       A7_JAVA      binário `java` (17+)
    A7_CLI_JAR      outro alpha7-cli.jar no lugar do que vem com a skill
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
JAR = AQUI / "alpha7-cli.jar"
# Windows: %APPDATA%\erp-alpha7 e %LOCALAPPDATA%\erp-alpha7. Demais: ~/.config e ~/.cache.
DIR_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or (os.name == "nt" and os.environ.get("APPDATA")) or Path.home() / ".config") / "erp-alpha7"
DIR_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or (os.name == "nt" and os.environ.get("LOCALAPPDATA")) or Path.home() / ".cache") / "erp-alpha7"
PY = "python" if os.name == "nt" else "python3"

# Comandos do CLI que só leem. Todo o resto grava e exige --confirmar-escrita.
COMANDOS_LEITURA = {"entity-get", "grupo-consumidores-pessoas", "unidades-negocio", "transferencia-sugestoes"}
# `invoke` é leitura quando o nome do método começa por um destes prefixos. É palpite
# pelo nome — por isso, na dúvida, o padrão é tratar como escrita.
PREFIXOS_LEITURA = (
    "find", "get", "busca", "list", "consult", "pesquis", "checa", "existe", "is",
    "count", "conta", "validate", "possui", "tem", "verifica",
)
WS_PATH = "/chinchila-chinchila-ejb-core/AtualizacaoClienteWebService"
SOAP_LISTA = (
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:atu="http://a7.net.br/chinchila-atualizacao-cliente"><soapenv:Body>'
    "<atu:getListaArquivosClienteDisponivelNoServidor/></soapenv:Body></soapenv:Envelope>"
)


def sair(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(2)


def aviso(msg: str) -> None:
    print(f"[alpha7-cli] {msg}", file=sys.stderr)


def ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


def separar_args(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    com_valor = {"--perfil", "--stdin", "--stdin-file", "--timeout"}
    sem_valor = {"--confirmar-escrita", "--preparar", "--servidores", "--baixar-libs", "--help", "-h"}
    opcoes: dict[str, str] = {}
    resto: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in com_valor:
            if i + 1 >= len(argv):
                sair(f"{a} precisa de um valor.")
            opcoes[a] = argv[i + 1]
            i += 2
        elif a in sem_valor:
            opcoes[a] = "1"
            i += 1
        elif a.startswith("--"):
            # O AlphaCli aceita --user/--pass/--host na linha de comando, mas aí a senha
            # aparece no `ps` e no histórico do shell. Aqui só entra pelo perfil.
            sair(f"Opção desconhecida: {a}. Credencial e destino vêm do perfil (alpha7_credenciais.py).")
        else:
            resto.append(a)
            i += 1
    return opcoes, resto


# ---------- runtime: libs, java, compilação ----------

def achar_a7pharma(cfg: dict[str, str]) -> Path | None:
    candidatos = [
        cfg.get("A7PHARMA_HOME"),
        str(Path.home() / "Alpha7" / "A7Pharma"),
        "/opt/Alpha7/A7Pharma",
        r"C:\Alpha7\A7Pharma",
    ]
    for c in candidatos:
        if c and (Path(c) / "releases" / "release.conf").exists():
            return Path(c)
    return None


def libs_da_instalacao(home: Path) -> Path | None:
    versao = (home / "releases" / "release.conf").read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
    lib = home / "releases" / versao / "lib"
    return lib if list(lib.glob("*.jar")) else None


def baixar_libs(cfg: dict[str, str]) -> Path:
    """Baixa os /lib/*.jar do servidor Alpha 7 — o mesmo WS do auto-update do cliente."""
    host, porta = cfg.get("A7_APP_HOST"), cfg.get("A7_APP_PORT", "8443")
    usuario, senha = cfg.get("A7_WS_USER"), cfg.get("A7_WS_PASS")
    if not host:
        sair("A7_APP_HOST não definido. Execute alpha7_credenciais.py (abre a janela de acesso).")
    if not usuario or not senha:
        sair(
            "Para baixar as libs do servidor faltam A7_WS_USER/A7_WS_PASS (usuário e senha do WS de\n"
            "atualização do cliente A7Pharma). Rode alpha7_credenciais.py --terminal --tecnicas, ou aponte\n"
            "A7PHARMA_HOME/A7_LIB para uma instalação do A7Pharma que já tenha as libs."
        )
    base = f"{'http' if porta == '8080' else 'https'}://{host}:{porta}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # o servidor da loja usa certificado autoassinado
    destino = DIR_CACHE / "libs" / re.sub(r"[^A-Za-z0-9._-]", "_", f"{host}_{porta}")
    destino.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(base + WS_PATH, data=SOAP_LISTA.encode(), headers={
        "Content-Type": "text/xml;charset=UTF-8",
        "SOAPAction": '""',
        "Authorization": "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode(),
    })
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        xml = r.read().decode("utf-8", errors="replace")
    nomes = [n for n in re.findall(r"<nome>([^<]*)</nome>", xml) if re.fullmatch(r"/lib/[^/]+\.jar", n)]
    if not nomes:
        sair("O servidor não devolveu nenhum /lib/*.jar (confira host, porta e credenciais do WS).")

    marca = destino / ".lista"
    assinatura = hashlib.sha256(xml.encode()).hexdigest()
    if marca.exists() and marca.read_text() == assinatura and len(list(destino.glob("*.jar"))) == len(nomes):
        return destino
    aviso(f"baixando {len(nomes)} libs do servidor (só na primeira vez ou quando a versão muda)...")
    for antigo in destino.glob("*.jar"):
        antigo.unlink()
    for nome in nomes:
        corpo = urllib.parse.urlencode({"type": "client", "file": nome}).encode()
        with urllib.request.urlopen(urllib.request.Request(base + "/web/download", data=corpo), timeout=300, context=ctx) as r:
            (destino / Path(nome).name).write_bytes(r.read())
    marca.write_text(assinatura)
    return destino


def achar_libs(cfg: dict[str, str], forcar_download: bool) -> tuple[Path, str]:
    if cfg.get("A7_LIB"):
        lib = Path(cfg["A7_LIB"])
        if not list(lib.glob("*.jar")):
            sair(f"A7_LIB não tem jars: {lib}")
        return lib, "A7_LIB"
    if not forcar_download:
        home = achar_a7pharma(cfg)
        if home:
            lib = libs_da_instalacao(home)
            if lib:
                return lib, f"A7Pharma instalado ({lib.parent.name})"
    return baixar_libs(cfg), "baixadas do servidor"


def versao_java(binario: str) -> int:
    try:
        saida = subprocess.run([binario, "-version"], capture_output=True, text=True, timeout=30).stderr
    except (OSError, subprocess.TimeoutExpired):
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', saida)
    if not m:
        return 0
    maior = int(m.group(1))
    return int(m.group(2) or 0) if maior == 1 else maior


def achar_java(cfg: dict[str, str]) -> str:
    exe = ".exe" if os.name == "nt" else ""
    candidatos: list[str] = []
    if cfg.get("A7_JAVA"):
        candidatos.append(cfg["A7_JAVA"])
    home = achar_a7pharma(cfg)
    if home:
        so = "windows" if os.name == "nt" else "linux"
        arq = "x64" if platform.machine().lower() in ("x86_64", "amd64") else platform.machine().lower()
        candidatos += sorted(glob.glob(str(home / "jre" / f"jre_17*-{so}-{arq}" / "bin" / f"java{exe}")), reverse=True)
    if shutil.which("java"):
        candidatos.append(shutil.which("java"))
    if os.environ.get("JAVA_HOME"):
        candidatos.append(str(Path(os.environ["JAVA_HOME"]) / "bin" / f"java{exe}"))
    for c in candidatos:
        if versao_java(c) >= 17:
            return c
    sair(
        "Não achei um Java 17 ou mais novo. O A7Pharma instalado traz um em <A7Pharma>/jre;\n"
        "sem ele, instale um JRE/JDK 17+ ou aponte A7_JAVA para o binário `java`."
    )


def preparar_classes(cfg: dict[str, str], libs: Path) -> str:
    """Devolve o caminho do jar do CLI."""
    jar = Path(cfg["A7_CLI_JAR"]) if cfg.get("A7_CLI_JAR") else JAR
    if not jar.exists():
        sair(f"alpha7-cli.jar não encontrado: {jar}")
    return str(jar)


# ---------- execução ----------

def listar_servidores(cfg: dict[str, str]) -> list[dict]:
    """Servidores do combo de login do A7Pharma desta máquina. Lista vazia se não der para ler."""
    try:
        if cfg.get("A7_LIB"):
            libs = Path(cfg["A7_LIB"])
        else:
            home = achar_a7pharma(cfg)
            libs = libs_da_instalacao(home) if home else None
        if not libs:
            return []
        r = subprocess.run(
            [achar_java(cfg), "-Dfile.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
             "-cp", os.pathsep.join([preparar_classes(cfg, libs), str(libs / "*")]), "AlphaCli", "listar-servidores"],
            input=b"", capture_output=True, timeout=60,
        )
        linhas = r.stdout.decode("utf-8", errors="replace").strip().splitlines()
        return json.loads(linhas[-1]).get("result") or [] if r.returncode == 0 and linhas else []
    except (SystemExit, OSError, ValueError, subprocess.TimeoutExpired):
        return []


def comando_grava(args: list[str]) -> bool:
    if args[0] in COMANDOS_LEITURA:
        return False
    if args[0] == "invoke" and len(args) >= 3:
        return not args[2].lower().startswith(PREFIXOS_LEITURA)
    return True


def ler_payload(opcoes: dict[str, str]) -> bytes:
    if "--stdin" in opcoes:
        dados = opcoes["--stdin"].encode("utf-8")
    elif "--stdin-file" in opcoes:
        dados = sys.stdin.buffer.read() if opcoes["--stdin-file"] == "-" else Path(opcoes["--stdin-file"]).read_bytes()
    else:
        return b""
    try:
        json.loads(dados)
    except ValueError as e:
        sair(f"O payload não é JSON válido: {e}")
    return dados


def main() -> None:
    # Console do Windows não é UTF-8 por padrão: sem isto, nome com acento vindo do ERP
    # derruba o print (ou sai trocado).
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    opcoes, args = separar_args(sys.argv[1:])
    if "--help" in opcoes or "-h" in opcoes or (not args and not {"--preparar", "--servidores"} & set(opcoes)):
        print(__doc__)
        sys.exit(0 if ("--help" in opcoes or "-h" in opcoes) else 2)

    perfil = opcoes.get("--perfil") or os.environ.get("A7_PERFIL") or "default"
    arquivo = DIR_CONFIG / f"{perfil}.env"
    cfg = {**ler_env(arquivo), **{k: v for k, v in os.environ.items() if k.startswith("A7") and v}}

    libs, origem = achar_libs(cfg, "--baixar-libs" in opcoes)
    if "--servidores" in opcoes:
        print(json.dumps(listar_servidores(cfg), ensure_ascii=False, indent=2))
        return
    java = achar_java(cfg)
    classes = preparar_classes(cfg, libs)

    if "--preparar" in opcoes:
        print(json.dumps({
            "perfil": perfil, "perfil_existe": arquivo.exists(), "servidor": cfg.get("A7_APP_SERVIDOR"), "host": cfg.get("A7_APP_HOST"),
            "usuario": cfg.get("A7_APP_USER"),
            "libs": str(libs), "origem_libs": origem, "java": java, "cli": classes,
        }, ensure_ascii=False, indent=2))
        return

    if not (cfg.get("A7_APP_HOST") and cfg.get("A7_APP_USER") and cfg.get("A7_APP_PASS")):
        sair(
            f"Perfil '{perfil}' sem servidor ou credencial ({arquivo}).\n"
            "Avise o usuário e execute (abre uma janela para ele escolher o servidor e informar usuário e\n"
            "senha, como no login do A7Pharma;\n"
            "use tempo limite de 10 minutos):\n"
            f"  {PY} {AQUI / 'alpha7_credenciais.py'}" + ("" if perfil == "default" else f" --perfil {perfil}")
        )
    if comando_grava(args) and "--confirmar-escrita" not in opcoes:
        sair(
            f"'{' '.join(args[:3])}' grava no ERP (ou não dá para saber pelo nome que só lê).\n"
            "Mostre ao usuário o que será gravado, em qual servidor, e só então repita o comando\n"
            "com --confirmar-escrita. Escrita não se repete às cegas: se a chamada falhar ou\n"
            "estourar o tempo, confira no ERP o que ficou gravado antes de tentar de novo."
        )

    payload = ler_payload(opcoes)
    filho = {k: v for k, v in os.environ.items() if not k.startswith("A7_")}
    filho.update({
        "A7_HOST": cfg["A7_APP_HOST"],
        "A7_PORT": cfg.get("A7_APP_PORT", "8443"),
        "A7_USER": cfg.get("A7_APP_USER", ""),
        "A7_PASS": cfg.get("A7_APP_PASS", ""),
        "A7_API_KEY": "",
        "A7_CONN_USER": cfg.get("A7_EJB_USER", ""),
        "A7_CONN_PASS": cfg.get("A7_EJB_PASS", ""),
    })
    cmd = [
        java, "--add-opens", "java.base/java.lang=ALL-UNNAMED",
        "-Dfile.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
        "-cp", os.pathsep.join([classes, str(libs / "*")]), "AlphaCli", *args,
    ]
    try:
        r = subprocess.run(cmd, input=payload, env=filho, capture_output=True, timeout=int(opcoes.get("--timeout", "300")))
    except subprocess.TimeoutExpired:
        sair(
            "A chamada passou do tempo limite e foi interrompida. Se era escrita, ela PODE ter sido\n"
            "gravada: confira no ERP antes de repetir."
        )
    saida = r.stdout.decode("utf-8", errors="replace").strip()
    # O stdout do CLI é uma linha de JSON; logs das libs podem vir antes dela.
    ultima = saida.splitlines()[-1] if saida else ""
    tem_json = True
    try:
        print(json.dumps(json.loads(ultima), ensure_ascii=False, indent=2))
    except ValueError:
        tem_json = False
        print(saida)
    # O {"error": ...} já diz a causa; a pilha do Java só aparece quando ele não veio
    # (o processo morreu antes) ou quando A7_DEBUG=1.
    if r.returncode != 0 and (not tem_json or os.environ.get("A7_DEBUG")):
        erro = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
        if erro:
            print("\n".join(erro[-40:]), file=sys.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
