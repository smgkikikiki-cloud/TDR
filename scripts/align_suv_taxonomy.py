from pathlib import Path

OLD_BODIES = 'const bodies = ["Sedan","Hatchback","Coupe","Crossover","SUV (Monocoque)","SUV (Ladder frame)","MPV","Pickup truck","Van"];'
NEW_BODIES = 'const bodies = ["Sedan","Hatchback","Coupe","Crossover","PPV","Offroad ladder frame","MPV","Pickup truck","Van"];'

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

for name in ("components/admin/ModelFormV12.tsx", "components/admin/ModelForm.tsx"):
    p = Path(name)
    if p.exists():
        s = p.read_text(encoding="utf-8").replace(OLD_BODIES, NEW_BODIES)
        p.write_text(s, encoding="utf-8")

p = Path("app/reports/page.tsx")
s = p.read_text(encoding="utf-8")
s = s.replace(
    '{ scope: "SUV โครงกระบะ (PPV)", question: "PPV รุ่นไหนกำลังกินส่วนแบ่งของรุ่นอื่นอยู่", pick: (r) => r.body_type === "SUV (Ladder frame)" },',
    '{ scope: "PPV พื้นฐานกระบะ", question: "PPV รุ่นไหนกำลังกินส่วนแบ่งของรุ่นอื่นอยู่", pick: (r) => r.body_type === "PPV" },',
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
