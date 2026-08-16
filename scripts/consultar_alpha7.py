#!/usr/bin/env python3
"""
Consulta somente leitura no ERP Alpha 7 (PostgreSQL).

Existe para que uma hipótese sobre o dado seja verificada em vez de afirmada de memória.
Recusa qualquer comando que não seja SELECT/WITH/SHOW/EXPLAIN — o Alpha 7 quase não tem
constraint declarada, então uma escrita acidental não bate em nenhuma rede de proteção.

Configuração (variáveis de ambiente):
    A7_HOST      host do PostgreSQL      (default: localhost)
    A7_PORT      porta                   (default: 5432)
    A7_USER      usuário somente leitura
    A7_PASSWORD  senha
    A7_DATABASE  base — lembre que o nome segue `<cliente>_esc_<data>` e ROTACIONA

Uso:
    python consultar_alpha7.py "SELECT * FROM unidadenegocio ORDER BY 1"
    python consultar_alpha7.py -f consulta.sql --json
    python consultar_alpha7.py --tabelas itemvenda      # colunas e índices
    python consultar_alpha7.py --bases                  # lista bases `_esc_` do servidor
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal
from datetime import date, datetime, time, timedelta

COMANDOS_PERMITIDOS = ("select", "with", "show", "explain", "table", "values")


def carregar_driver():
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore

        return "psycopg2", psycopg2
    except ImportError:
        pass
    try:
        import psycopg  # type: ignore

        return "psycopg3", psycopg
    except ImportError:
        sys.exit(
            "Nenhum driver PostgreSQL encontrado.\n"
            "Instale um deles:  pip install psycopg2-binary   (ou)   pip install psycopg[binary]"
        )


def validar_somente_leitura(sql: str) -> None:
    limpo = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    limpo = re.sub(r"--[^\n]*", " ", limpo)

    statements = [s.strip() for s in limpo.split(";") if s.strip()]
    if not statements:
        sys.exit("Consulta vazia.")
    for stmt in statements:
        primeira = stmt.split(None, 1)[0].lower()
        if primeira not in COMANDOS_PERMITIDOS:
            sys.exit(
                f"Bloqueado: '{primeira.upper()}' não é comando de leitura.\n"
                "Este script só executa SELECT / WITH / TABLE / VALUES / SHOW / EXPLAIN.\n"
                "Escrita no Alpha 7 é possível, mas exige confirmação explícita do cliente e\n"
                "replicar à mão as invariantes que o banco não declara (ver referências)."
            )
    if len(statements) > 1:
        sys.exit("Envie um comando por vez — statement múltiplo não é aceito.")


def serializar(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, timedelta):
        return str(valor)
    if isinstance(valor, (bytes, memoryview)):
        return bytes(valor).decode("utf-8", "replace")
    return valor


def imprimir_tabela(linhas, limite_col=48):
    if not linhas:
        print("(nenhuma linha)")
        return
    colunas = list(linhas[0].keys())

    def celula(v):
        s = "" if v is None else str(v)
        return s[: limite_col - 1] + "…" if len(s) > limite_col else s

    larguras = {c: max(len(c), *(len(celula(l.get(c))) for l in linhas)) for c in colunas}
    print(" | ".join(c.ljust(larguras[c]) for c in colunas))
    print("-+-".join("-" * larguras[c] for c in colunas))
    for l in linhas:
        print(" | ".join(celula(l.get(c)).ljust(larguras[c]) for c in colunas))
    print(f"\n({len(linhas)} linha(s))")


SQL_COLUNAS = """
SELECT c.column_name        AS coluna,
       c.data_type          AS tipo,
       c.character_maximum_length AS tamanho,
       c.is_nullable        AS aceita_nulo,
       c.column_default     AS padrao
FROM information_schema.columns c
WHERE c.table_name = %s
ORDER BY c.ordinal_position
"""

SQL_INDICES = """
SELECT indexname AS indice, indexdef AS definicao
FROM pg_indexes
WHERE tablename = %s
ORDER BY indexname
"""

SQL_BASES = """
SELECT datname AS base, pg_size_pretty(pg_database_size(datname)) AS tamanho
FROM pg_database
WHERE datistemplate = false
ORDER BY datname
"""


def main() -> None:
    p = argparse.ArgumentParser(description="Consulta somente leitura no ERP Alpha 7 (PostgreSQL).")
    p.add_argument("sql", nargs="?", help="SQL a executar, ou '-' para ler do stdin")
    p.add_argument("-f", "--arquivo", help="arquivo .sql a executar")
    p.add_argument("--tabelas", metavar="TABELA", help="descreve colunas e índices da tabela")
    p.add_argument("--bases", action="store_true", help="lista as bases do servidor (achar a base `_esc_` corrente)")
    p.add_argument("--json", action="store_true", help="saída em JSON em vez de tabela")
    p.add_argument("--limite", type=int, default=200, help="máximo de linhas exibidas (0 = tudo)")
    p.add_argument("--timeout", type=int, default=120, help="statement_timeout em segundos")
    p.add_argument("--host", default=os.getenv("A7_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(os.getenv("A7_PORT", "5432")))
    p.add_argument("--user", default=os.getenv("A7_USER"))
    p.add_argument("--password", default=os.getenv("A7_PASSWORD"))
    p.add_argument("--database", default=os.getenv("A7_DATABASE", "postgres"))
    args = p.parse_args()

    if not args.user:
        sys.exit("Defina A7_USER/A7_PASSWORD (ou passe --user/--password). Use um usuário somente leitura.")

    params: list = []
    if args.bases:
        consultas = [(SQL_BASES, [])]
    elif args.tabelas:
        if not re.fullmatch(r"[A-Za-z0-9_]+", args.tabelas):
            sys.exit("Nome de tabela inválido.")
        consultas = [(SQL_COLUNAS, [args.tabelas]), (SQL_INDICES, [args.tabelas])]
    else:
        if args.arquivo:
            sql = open(args.arquivo, encoding="utf-8").read()
        elif args.sql == "-" or (args.sql is None and not sys.stdin.isatty()):
            sql = sys.stdin.read()
        elif args.sql:
            sql = args.sql
        else:
            p.error("informe a SQL, -f arquivo, --tabelas, --bases, ou envie por stdin")
        validar_somente_leitura(sql)
        consultas = [(sql.strip().rstrip(";"), [])]

    nome, driver = carregar_driver()
    conn = driver.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        dbname=args.database,
        connect_timeout=15,
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
    except Exception:
        pass

    try:
        for q, ps in consultas:
            if nome == "psycopg2":
                import psycopg2.extras  # type: ignore

                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            else:
                import psycopg.rows  # type: ignore

                cur = conn.cursor(row_factory=psycopg.rows.dict_row)
            try:
                cur.execute(f"SET statement_timeout = {int(args.timeout) * 1000}")
                cur.execute("SET TIME ZONE 'America/Sao_Paulo'")
                cur.execute(q, ps or None)
                brutas = cur.fetchall()
            finally:
                cur.close()

            linhas = [{c: serializar(v) for c, v in dict(r).items()} for r in brutas]
            truncado = 0
            if args.limite and len(linhas) > args.limite:
                truncado = len(linhas) - args.limite
                linhas = linhas[: args.limite]

            if len(consultas) > 1:
                print(f"\n== {'índices' if 'pg_indexes' in q else 'colunas'} ==")
            if args.json:
                print(json.dumps(linhas, ensure_ascii=False, indent=2, default=str))
            else:
                imprimir_tabela(linhas)
            if truncado:
                print(f"… {truncado} linha(s) omitida(s) — use --limite 0 para ver tudo.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
