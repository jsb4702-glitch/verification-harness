---
name: reliability
description: 신뢰성·내구성·환경 설계. MTBF 예측, 피로수명(Miner·Basquin·Rainflow), 진동/충격(PSD·SRS·Steinberg), 방수밀봉(IP67/68·O-ring). "MTBF", "피로 FoS", "Miner 누적손상", "진동 시험", "충격 SRS", "방수 IP67", "O-ring 압축률", "고유진동수 fn" 질의 시 호출.
---

# 신뢰성/진동충격/방수밀봉 (KB 6.7)

## 신뢰성
- MTBF 🟢 MIL-HDBK-217F(폐지·관행)/FIDES/Telcordia SR-332 · FMECA 🟢 MIL-STD-1629A(Cancelled 1998·관행)
- 피로 Basquin·MMPDS-19·Miner(D=1, 보수 D=0.7)·Rainflow·Kt필수·**FoS≥4** · 마모 Archard·ISO 281:2007 L10 · Weibull β<1/≈1/>1

## 진동/충격
- fn ≥ 시험상한×1.4 (휴대/차량≥50Hz, 항공≥100Hz)
- 🟢 MIL-STD-810H 514.8 PSD, Steinberg 3σ(4th ed.) · 516.8 SRS, 접착마운트 충격검토
- 절연 TR<0.1, 절연 후 광축변위 검증

## 방수/밀봉
- IP67 O-ring 압축률 15~25%, IP68 Ra≤1.6μm · 🟢 AS568/ISO 3601, NBR/EPDM/FKM/FFKM
- Vent(Gore-Tex), N₂/Desiccant

## 규율
피로·진동응답·임계변형 = **안전임계** → G9 2단(오차범위)+gemini-review 이종검증. 물성 실측값은 web_search/MMPDS 확인.
