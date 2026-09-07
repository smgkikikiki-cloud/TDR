from pathlib import Path

p = Path("app/models/page.tsx")
s = p.read_text(encoding="utf-8")
s = s.replace(
    '  { value: "Crossover", label: "ครอสโอเวอร์", group: "SUV" },\n  { value: "SUV (Monocoque)", label: "SUV โมโนค็อก", group: "SUV" },\n  { value: "SUV (Ladder frame)", label: "SUV โครงกระบะ (PPV)", group: "SUV" },',
    '  { value: "Crossover", label: "ครอสโอเวอร์ / SUV โมโนค็อก", group: "SUV" },\n  { value: "PPV", label: "PPV พื้นฐานกระบะ", group: "SUV" },\n  { value: "Offroad ladder frame", label: "SUV ออฟโรดโครงแชสซีส์", group: "SUV" },',
)
s = s.replace(
    'const BODY_QUICK = ["Pickup truck", "SUV (Ladder frame)", "Crossover", "SUV (Monocoque)", "Sedan", "Hatchback", "MPV", "Van", "Coupe"];',
    'const BODY_QUICK = ["Pickup truck", "PPV", "Crossover", "Offroad ladder frame", "Sedan", "Hatchback", "MPV", "Van", "Coupe"];',
)
p.write_text(s, encoding="utf-8")

p = Path("components/admin/ModelFormV12.tsx")
s = p.read_text(encoding="utf-8")
s = s.replace(
    'const bodies = ["Sedan","Hatchback","Coupe","Crossover","SUV (Monocoque)","SUV (Ladder frame)","MPV","Pickup truck","Van"];',
    'const bodies = ["Sedan","Hatchback","Coupe","Crossover","PPV","Offroad ladder frame","MPV","Pickup truck","Van"];',
)
p.write_text(s, encoding="utf-8")

legacy = []
for root in (Path("app"), Path("components"), Path("lib")):
    for f in root.rglob("*"):
        if f.suffix not in {".ts", ".tsx"}:
            continue
        text = f.read_text(encoding="utf-8")
        if "SUV (Monocoque)" in text or "SUV (Ladder frame)" in text:
            legacy.append(str(f))
if legacy:
    raise SystemExit(f"legacy runtime SUV body values remain: {legacy}")
