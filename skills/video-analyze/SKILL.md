---
name: video-analyze
description: >-
  Use this skill whenever a user points to a video — a local file (.mp4/.mov/.mkv/.avi 등)
  or a video URL (YouTube, Vimeo, 웹 링크) — and wants to know what's *in* it. Triggers on
  intents like: 요약/무슨 내용/이거 무슨 영상, 받아써줘·전사·누가 무슨 말 했는지,
  타임스탬프·챕터 따줘, 화면 속 객체·텍스트·장면 뽑아줘, 특정 구간 분석. Covers
  회의녹화·강의·튜토리얼·시연·현장영상·제품소개 등 영상이 입력으로 들어오는 거의 모든 이해/분석 요청.
  Pick this even when the user is casual ("봐주라", "리스트업 해줘") or only gives a
  filename/URL with an analysis ask — the video + "understand its content" combo is the signal.
  Do NOT use for: audio-only files (.mp3 등) 단순 전사, 이미지 한 장 분석,
  영상 포맷 변환/압축/화질조정, 다운로드만(분석 없이), 또는 영상 자체가 아닌 댓글·메타데이터 분석.
  핵심 = 영상의 시각+음성 내용을 해석하려는 의도일 때만.
---

# video-analyze

영상은 raw 입력을 그대로 LLM에 못 넣는다. 이 스킬은 두 경로로 그 벽을 넘는다 — 데이터 민감도에 따라 갈린다.

## ⛔ 가장 먼저: 민감도 분기 (이게 경로를 정한다)

영상에 **수출통제 대상·사내기밀·개인정보**가 섞일 가능성이 조금이라도 있나?

- **있거나 / 모르겠으면 → 로컬 경로 (기본값).** 데이터가 외부로 1바이트도 안 나간다.
- **확실히 일반 공개영상(튜토리얼·뉴스·제품홍보 등)일 때만 → Gemini 경로.** 더 빠르고 싸지만 **영상이 Google로 전송**된다.

판단이 애매하면 사용자에게 **"이 영상 외부(Google) 전송해도 되는 일반자료 맞나?"** 한 줄 물어보고 결정하라. 기본은 항상 안전한 로컬이다. 이건 하네스 L3 수출통제 게이트와 직결된다 — 민감영상을 Gemini로 보내는 사고를 원천 차단하는 게 이 스킬의 1순위 규율.

## 최초 1회: 의존성 확인

로컬 경로는 venv가 필요하다. `scripts/.venv` 가 없으면 먼저:
```bash
bash scripts/setup.sh
```
(ffmpeg 필요 + yt-dlp·faster-whisper를 pip venv에 설치. brew는 Xcode 라이선스로 막힐 수 있어 venv를 쓴다.) Gemini 경로는 `~/.config/secrets.env` 의 `GEMINI_API_KEYS` 만 있으면 된다(setup 불필요). 키는 AQ 형식이어야 한다 — 구형 AIza 표준키는 2026-09 부터 거부된다. 단일 `GEMINI_API_KEY` 도 로테이터가 읽지만 폴백 경로다.

---

## 경로 A: 로컬 (민감자료 / 기본)

```bash
python3 scripts/local_analyze.py "<URL 또는 파일경로>" --out <작업디렉토리>
```
주요 옵션:
- `--model small` (기본). 한국어 전문용어는 `small` 권장. `base`는 빠르지만 부정확, `medium`은 정확하나 느림.
- `--hint "도메인 용어..."` — **이게 한국어 전사 품질의 핵심.** whisper는 동음이의 한자어(계수↔개수, 변위↔편의)와 외래 전문어(게르마늄)를 자주 틀리는데, 도메인 용어를 힌트로 주면 거의 100% 회복된다. 기본값은 기계설계 용어. 영상 주제가 다르면 그에 맞는 용어로 바꿔 줘라(예: 의료·법률·SW).
- `--min-frames 4` — 씬검출이 이보다 적게 잡으면(긴 정적 영상) 균등간격으로 자동 보강한다.
- `--lang ko|en|auto` (기본 auto).

스크립트는 JSON을 stdout으로 낸다: `frames`(추출된 프레임 절대경로 배열), `transcript`(타임스탬프별 음성), `frame_method`.

**그다음 네가 할 일 (중요):** 스크립트는 시각 해석을 안 한다. 반환된 `frames` 경로들을 **Read 툴로 직접 열어** 화면 내용(객체·텍스트·도표·UI)을 판독하고, `transcript`(음성)와 합쳐서 종합 분석을 작성하라. 프레임이 시각, transcript가 청각 — 둘을 교차해야 영상을 이해한 것이다.

## 경로 B: Gemini (일반 공개영상 전용)

```bash
python3 scripts/gemini_analyze.py "<URL 또는 파일경로>" --prompt "원하는 분석 질문"
```
- URL은 다운로드 없이 직접 투입된다. 로컬파일은 File API로 업로드된다.
- Gemini가 영상+오디오를 네이티브로 처리하므로 프레임 추출·전사 불필요. 결과 `analysis` 텍스트를 받아 정리만 하면 된다.
- `--model` 기본 `gemini-2.5-flash`(무료티어). 정밀이 필요하면 `gemini-2.5-pro`.
- **HTTP 429(quota 초과) 시 로컬 경로로 자동 fallback.** 무료티어는 일당 호출수 제한(flash 기준 하루 약 20회)이 있어 자주 막힌다. 일반영상이면 로컬 경로(경로 A)로 그대로 넘어가면 된다 — 결과 품질은 거의 동등하고 데이터도 안전하다. 즉 Gemini는 "되면 빠른 보너스", 안 되면 로컬이 항상 받쳐준다.

---

## 출력 형식

분석 결과는 하네스 규율대로 — BLUF 첫 줄, 근거 병기, 불확실한 건 표시. 특히:
- 전사에서 못 알아들은 구간, whisper 오인식 의심 구간은 ⚠️로 표시(특히 고유명사·수치·전문용어). 사용자가 영상 원본을 갖고 있으니 의심구간만 짚어주면 본인이 확인 가능.
- 화면의 수치·규격번호·PN을 프레임에서 읽을 때, 흐릿하거나 추정이면 단정하지 말 것(G4). "프레임상 ~로 보임(저해상도, 확인필요)".
- 타임스탬프는 transcript의 `t`(초)와 프레임을 함께 활용해 "0:14 — …" 형식으로.

## 함정 (PoC에서 실측한 것)

| 함정 | 대응 |
|------|------|
| 한국어 전문용어를 whisper가 박살냄 | `--hint`에 도메인 용어 주입(필수). `--model small` 이상 |
| 긴 정적 영상 → 씬검출 1~2장만, 시각정보 누락 | `--min-frames`로 균등간격 자동 보강(스크립트 내장) |
| yt-dlp가 일부 고화질 포맷 못 받음(JS런타임 경고) | 분석엔 360p로 충분. 고화질 필요시 `deno` 설치 |
| 민감영상을 Gemini로 전송 | 기본 로컬. Gemini는 명시적 일반영상 확인 후에만 |
