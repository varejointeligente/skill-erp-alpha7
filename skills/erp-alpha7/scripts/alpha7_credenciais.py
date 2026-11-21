#!/usr/bin/env python3
"""
Pergunta em qual servidor do Alpha 7 entrar, o usuário e a senha, e grava num perfil
local para o `alpha7_cli.py` usar.

Abre uma JANELA igual ao login do A7Pharma: a pessoa escolhe o servidor na mesma lista
que o A7Pharma mostra, digita usuário e senha e clica em Salvar. A senha vai da janela
direto para o arquivo do perfil — não aparece na saída deste script nem na conversa com o
Claude. Por isso o Claude pode (e deve) executar este script ele mesmo e pedir ao usuário
que preencha a janela; o que ele não faz é pedir a senha no chat.

    python alpha7_credenciais.py                  # janela, perfil "default"  (python3 no Linux/macOS)
    python alpha7_credenciais.py --perfil redeX   # um perfil por rede/servidor
    python alpha7_credenciais.py --mostrar        # o que está gravado, sem os segredos
    python alpha7_credenciais.py --terminal       # pergunta no terminal em vez da janela
    python alpha7_credenciais.py --terminal --tecnicas   # idem + EJB e WS de atualização

A janela espera até 10 minutos e se fecha sozinha. Saída: "gravado" (exit 0),
"cancelado" (exit 3) ou a razão de não ter aberto (exit 1).

A lista de servidores vem do cadastro do A7Pharma desta máquina. Sem A7Pharma instalado
(ou sem servidor cadastrado nele), a janela pede o endereço e a porta.

O perfil fica fora de qualquer repositório: %APPDATA%/erp-alpha7/<perfil>.env no Windows
(protegido pelo perfil do usuário do Windows) e ~/.config/erp-alpha7/<perfil>.env nos
demais, com permissão 600.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alpha7_cli  # noqa: E402  (acha o A7Pharma e lê a lista de servidores dele)

DIR_CONFIG = alpha7_cli.DIR_CONFIG
PY = alpha7_cli.PY
SEGREDOS = {"A7_APP_PASS", "A7_APP_API_KEY", "A7_EJB_PASS", "A7_WS_PASS"}
ESPERA_JANELA_MS = 10 * 60 * 1000


def ler(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip()
    return valores


def gravar(arquivo: Path, cfg: dict[str, str]) -> None:
    DIR_CONFIG.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR_CONFIG, 0o700)
    descritor = os.open(arquivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as f:
        f.write("# Credenciais do Alpha 7 para o alpha7_cli.py. Não versionar, não colar em conversa.\n")
        for chave, valor in cfg.items():
            if valor:
                f.write(f"{chave}={valor}\n")
    os.chmod(arquivo, 0o600)


def aplicar(cfg: dict[str, str], servidor: dict | None, host: str, porta: str, usuario: str, senha: str) -> str | None:
    """Põe os valores em cfg. Devolve a mensagem de erro, ou None se está tudo certo.

    `servidor` é o item escolhido na lista do A7Pharma; sem lista, valem `host` e `porta`.
    """
    if servidor:
        host, porta, nome = str(servidor["host"]), str(servidor["porta"]), str(servidor.get("descricao") or servidor["host"])
    else:
        host, porta = host.strip(), porta.strip() or "8443"
        # Colar a URL inteira é o engano mais comum: fica só o host.
        host = re.sub(r"^[a-z+]+://", "", host, flags=re.I).split("/")[0]
        if ":" in host and host.rsplit(":", 1)[1].isdigit():
            host, porta = host.rsplit(":", 1)
        nome = host
    usuario = usuario.strip()
    # A senha gravada só vale para o mesmo servidor e usuário: trocou um deles, digita de novo.
    mesmo = host == cfg.get("A7_APP_HOST") and usuario == cfg.get("A7_APP_USER")
    senha = senha or (cfg.get("A7_APP_PASS", "") if mesmo else "")
    if not host:
        return "Escolha o servidor." if servidor is None and not porta else "Informe o servidor."
    if not porta.isdigit():
        return "A porta deve ser um número."
    if not usuario:
        return "Informe o usuário."
    if not senha:
        return "Informe a senha."
    cfg.pop("A7_APP_API_KEY", None)
    cfg.update(A7_APP_SERVIDOR=nome, A7_APP_HOST=host, A7_APP_PORT=porta, A7_APP_USER=usuario, A7_APP_PASS=senha)
    return None


# ---------- janela ----------

def montar_janela(cfg: dict[str, str], perfil: str, servidores: list[dict], resultado: dict):
    import tkinter as tk
    from tkinter import ttk

    raiz = tk.Tk()
    raiz.title("Alpha 7 — acesso ao ERP")
    raiz.resizable(False, False)
    quadro = ttk.Frame(raiz, padding=16)
    quadro.grid()

    ttk.Label(quadro, text="Acesso ao Alpha 7", font=("", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(
        quadro, wraplength=380, justify="left",
        text=("Entre como você entra no A7Pharma: mesmo servidor, usuário e senha. "
              "A senha fica guardada só neste computador e não é enviada para a conversa."),
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))

    v = {nome: tk.StringVar() for nome in ("servidor", "host", "porta", "usuario", "senha")}
    v["usuario"].set(cfg.get("A7_APP_USER", ""))
    entradas = {}

    def linha(n: int, rotulo: str, widget) -> None:
        ttk.Label(quadro, text=rotulo).grid(row=n, column=0, sticky="w", padx=(0, 10), pady=3)
        widget.grid(row=n, column=1, sticky="we", pady=3)

    if servidores:
        # Descrição repetida ganha o endereço ao lado, para as duas opções não ficarem iguais.
        vistos: dict[str, int] = {}
        for s in servidores:
            vistos[s["descricao"]] = vistos.get(s["descricao"], 0) + 1
        rotulos = [s["descricao"] if vistos[s["descricao"]] == 1 else f'{s["descricao"]} ({s["host"]})' for s in servidores]
        combo = ttk.Combobox(quadro, textvariable=v["servidor"], values=rotulos, state="readonly", width=28)
        atual = [i for i, s in enumerate(servidores) if str(s["host"]) == cfg.get("A7_APP_HOST") and str(s["porta"]) == cfg.get("A7_APP_PORT", "8443")]
        # Sem perfil gravado, vem o primeiro da lista, como no login do A7Pharma.
        combo.current(atual[0] if atual else 0)
        linha(2, "Servidor", combo)
        entradas["servidor"] = combo
    else:
        ttk.Label(
            quadro, wraplength=380, justify="left", foreground="#666",
            text="Nenhum servidor cadastrado no A7Pharma deste computador. Informe o endereço que o suporte passou.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v["host"].set(cfg.get("A7_APP_HOST", ""))
        v["porta"].set(cfg.get("A7_APP_PORT", "8443"))
        entradas["host"] = ttk.Entry(quadro, textvariable=v["host"], width=30)
        linha(3, "Servidor (endereço ou IP)", entradas["host"])
        linha(4, "Porta", ttk.Entry(quadro, textvariable=v["porta"], width=30))

    entradas["usuario"] = ttk.Entry(quadro, textvariable=v["usuario"], width=30)
    linha(5, "Usuário", entradas["usuario"])
    entradas["senha"] = ttk.Entry(quadro, textvariable=v["senha"], width=30, show="•")
    linha(6, "Senha" + (" (em branco mantém a atual)" if cfg.get("A7_APP_PASS") else ""), entradas["senha"])

    erro = ttk.Label(quadro, text="", foreground="#b00020", wraplength=380, justify="left")
    erro.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def salvar(*_):
        escolhido = None
        if servidores:
            i = entradas["servidor"].current()
            if i < 0:
                erro.config(text="Escolha o servidor.")
                return
            escolhido = servidores[i]
        falha = aplicar(cfg, escolhido, v["host"].get(), v["porta"].get(), v["usuario"].get(), v["senha"].get())
        if falha:
            erro.config(text=falha)
            return
        resultado["ok"] = True
        raiz.destroy()

    botoes = ttk.Frame(quadro)
    botoes.grid(row=9, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(botoes, text="Cancelar", command=raiz.destroy).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(botoes, text="Salvar", command=salvar).grid(row=0, column=1)
    raiz.bind("<Return>", salvar)
    raiz.bind("<Escape>", lambda *_: raiz.destroy())
    if perfil != "default":
        ttk.Label(quadro, text=f"Perfil: {perfil}", foreground="#666").grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # Na frente das outras janelas: quem abriu foi o Claude, e a pessoa está olhando o chat.
    raiz.update_idletasks()
    x = (raiz.winfo_screenwidth() - raiz.winfo_reqwidth()) // 2
    y = (raiz.winfo_screenheight() - raiz.winfo_reqheight()) // 3
    raiz.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    raiz.attributes("-topmost", True)
    raiz.after(600, lambda: raiz.attributes("-topmost", False))
    raiz.after(ESPERA_JANELA_MS, raiz.destroy)
    if servidores and entradas["servidor"].current() < 0:
        entradas["servidor"].focus_set()
    elif not servidores and not v["host"].get():
        entradas["host"].focus_set()
    else:
        entradas["senha" if v["usuario"].get() else "usuario"].focus_set()
    return raiz, salvar, v, entradas


def pela_janela(cfg: dict[str, str], perfil: str, servidores: list[dict]) -> bool:
    resultado: dict = {}
    try:
        raiz = montar_janela(cfg, perfil, servidores, resultado)[0]
    except Exception as e:  # sem tkinter, sem tela (servidor, SSH), etc.
        sys.exit(
            f"Não foi possível abrir a janela ({type(e).__name__}: {e}).\n"
            "Sem tela gráfica, a pessoa precisa rodar no terminal dela:\n"
            f"  {PY} {Path(__file__).resolve()} --terminal" + ("" if perfil == "default" else f" --perfil {perfil}")
        )
    raiz.mainloop()
    return bool(resultado.get("ok"))


# ---------- terminal ----------

def perguntar(rotulo: str, atual: str = "", segredo: bool = False) -> str:
    if segredo:
        return getpass.getpass(f"{rotulo}{' [Enter mantém a gravada]' if atual else ''}: ") or atual
    return input(f"{rotulo}{f' [{atual}]' if atual else ''}: ").strip() or atual


def pelo_terminal(cfg: dict[str, str], perfil: str, servidores: list[dict], tecnicas: bool) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("--terminal precisa de um terminal interativo (a senha é digitada sem eco). Sem ele, use a janela.")
    print(f"Acesso ao Alpha 7 — perfil '{perfil}'\n")
    escolhido, host, porta = None, "", ""
    if servidores:
        for i, s in enumerate(servidores, start=1):
            print(f"  {i}. {s['descricao']}")
        n = perguntar("Servidor (número)")
        if not n.isdigit() or not 1 <= int(n) <= len(servidores):
            sys.exit("Número de servidor inválido.")
        escolhido = servidores[int(n) - 1]
    else:
        host = perguntar("Servidor (endereço ou IP)", cfg.get("A7_APP_HOST", ""))
        porta = perguntar("Porta", cfg.get("A7_APP_PORT", "8443"))
    usuario = perguntar("Usuário", cfg.get("A7_APP_USER", ""))
    falha = aplicar(cfg, escolhido, host, porta, usuario, getpass.getpass("Senha: "))
    if falha:
        sys.exit(falha)
    if tecnicas:
        print("\nCredenciais técnicas do cliente A7Pharma (Enter pula):")
        print("- EJB: só se o servidor não usar o padrão do cliente.")
        print("- WS de atualização: só para baixar as libs do servidor, quando não há A7Pharma instalado aqui.")
        for chave, rotulo, segredo in (
            ("A7_EJB_USER", "Usuário da conexão EJB", False),
            ("A7_EJB_PASS", "Senha da conexão EJB", True),
            ("A7_WS_USER", "Usuário do WS de atualização", False),
            ("A7_WS_PASS", "Senha do WS de atualização", True),
        ):
            cfg[chave] = perguntar(rotulo, cfg.get(chave, ""), segredo=segredo)
    return True


def main() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return
    perfil = "default"
    if "--perfil" in args:
        i = args.index("--perfil")
        if i + 1 >= len(args):
            sys.exit("--perfil precisa de um nome.")
        perfil = args[i + 1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", perfil):
        sys.exit("Nome de perfil só com letras, números, ponto, hífen e sublinhado.")
    arquivo = DIR_CONFIG / f"{perfil}.env"
    cfg = ler(arquivo)

    if "--mostrar" in args:
        if not cfg:
            print(f"Perfil '{perfil}' ainda não existe ({arquivo}).")
            return
        for chave, valor in cfg.items():
            print(f"{chave}={'<gravado>' if chave in SEGREDOS else valor}")
        return

    servidores = alpha7_cli.listar_servidores({**cfg, **{k: v for k, v in os.environ.items() if k.startswith("A7") and v}})
    if "--terminal" in args:
        ok = pelo_terminal(cfg, perfil, servidores, "--tecnicas" in args)
    else:
        ok = pela_janela(cfg, perfil, servidores)
    if not ok:
        print("cancelado: a janela foi fechada sem salvar; nada foi alterado.")
        sys.exit(3)
    gravar(arquivo, cfg)
    print(f"gravado: perfil '{perfil}', servidor {cfg['A7_APP_SERVIDOR']} ({cfg['A7_APP_HOST']}:{cfg['A7_APP_PORT']}), usuário {cfg['A7_APP_USER']}.")


if __name__ == "__main__":
    main()
