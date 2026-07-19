#!/usr/bin/env python3
"""UserPromptSubmit 훅: 코드베이스/구조 질의 + graphify-out/ 존재 시 graphify 우선 사용 지시 주입."""
import json, sys, os, re

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

prompt = (d.get("prompt") or "")
cwd = d.get("cwd") or os.getcwd()

# 코드베이스/아키텍처/파일관계/구조 관련 키워드
KW = re.compile(
    r"코드\s*베이스|아키텍처|파일\s*관계|모듈\s*관계|프로젝트\s*구조|"
    r"구조\s*파악|의존성|호출\s*관계|콜\s*그래프|"
    r"codebase|architecture|file\s*relation|project\s*structure|"
    r"dependenc|call\s*graph|how.*(connect|relate|wired)|where.*defined",
    re.IGNORECASE,
)

graph_dir = os.path.join(cwd, "graphify-out")
if os.path.isdir(graph_dir) and KW.search(prompt):
    ctx = ("graphify-out/ 가 존재하고 이 프롬프트는 코드베이스/구조 질의로 감지됨. "
           "원본 파일을 직접 탐색하기 전에 graphify 스킬을 먼저 사용하라 — "
           'graphify query "<질문>" 으로 범위 서브그래프를 받고, 필요시 explain/path 사용. '
           "이 지시는 코드 탐색을 수행하는 서브에이전트 프롬프트에도 포함하라.")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ctx,
        }
    }))
sys.exit(0)
