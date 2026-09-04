#!/usr/bin/env python3
"""
llm_lock — 로컬 LLM 배치 잡 상호배제 락 (2026-07-22, 경합 근본수리).

문제: ollama가 단일 창구인데 소비자(레이더·매트릭스·주간FT·수확체인)가 무조정으로
겹치면 모델 스왑 경합으로 탐침당 수 분씩 걸린다(07-22 실측: 경합 시 180초+ 대
단독 6초). 처방: 배치 잡은 전부 이 래퍼로 실행 — 한 번에 하나만.

사용:
  python3 llm_lock.py --name <잡이름> [--wait 초(기본 7200)] -- <명령...>

동작:
  ~/.claude/tools/llm-lock/gpu.lock 배타 락을 잡을 때까지 대기(폴링 15초).
  잡으면 명령 실행, 종료코드 그대로 전달. 락은 프로세스 종료 시 커널이 자동 해제
  (크래시에도 잔류 락 없음). 보유자 정보는 lock.info, 이력은 lock.log.

비대상: 짧은 단발 호출(엔트로피 섀도 3샘플 등)은 락 없이 그냥 간다 —
  배치 잡이 락을 잡고 있어도 몇 초 큐잉으로 흡수되는 수준이라 직렬화 비용이 더 크다.
"""
import argparse, fcntl, json, os, subprocess, sys, time

DIR = os.path.dirname(os.path.abspath(__file__))
LOCKFILE = os.path.join(DIR, "gpu.lock")
INFOFILE = os.path.join(DIR, "lock.info")
LOGFILE = os.path.join(DIR, "lock.log")


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(f"[llm-lock] {line}", flush=True)
    try:
        with open(LOGFILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def holder():
    try:
        return json.load(open(INFOFILE)).get("name", "?")
    except Exception:
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--wait", type=int, default=7200)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        sys.exit("[llm-lock] 실행할 명령이 없다")

    fd = open(LOCKFILE, "w")
    t0 = time.time()
    waited = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if not waited:
                log(f"{a.name}: 대기 시작 (보유자: {holder()})")
                waited = True
            if time.time() - t0 > a.wait:
                log(f"{a.name}: {a.wait}초 초과 — 포기")
                sys.exit(75)
            time.sleep(15)

    try:
        json.dump({"name": a.name, "pid": os.getpid(),
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(INFOFILE, "w"))
    except Exception:
        pass
    log(f"{a.name}: 락 획득({round(time.time()-t0)}초 대기) → 실행: {' '.join(cmd)[:120]}")

    env = dict(os.environ, LLM_LOCK_HELD="1")
    rc = subprocess.run(cmd, env=env).returncode
    log(f"{a.name}: 종료 rc={rc} (점유 {round(time.time()-t0)}초)")
    sys.exit(rc)


if __name__ == "__main__":
    main()
