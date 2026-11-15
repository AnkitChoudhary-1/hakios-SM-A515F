from pathlib import Path

def main():
    root = Path("/opt/a51-hakios/src/hakios-xnu-kernel")
    matches = []
    for p in root.rglob("*"):
        name = p.name.lower()
        if any(k in name for k in ["serial", "uart", "console"]) and p.suffix in (".c", ".h", ".s", ".S"):
            matches.append(str(p.relative_to(root)))
    for m in sorted(matches):
        print(m)

if __name__ == "__main__":
    main()

