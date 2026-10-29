#!/usr/bin/env python3
"""Generate or edit one image with Codex's built-in imagegen skill and save it.

  codex_image.py --out /abs/mockups/home-a.png [--ref current.png ...] [--model fast|<slug>]
                 [--prompt-file FILE | PROMPT | - (stdin)]

One image per run; run several in the background for variants. --ref attaches
reference images (a screenshot of the current UI for a redesign, a brand sheet);
with refs the prompt should say what each one is for. --out is never overwritten:
an existing name gets -v2, -v3, ... The saved path is printed on the last line.
Uses Codex's own image tool (ChatGPT plan), never the API fallback.
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile, time

FAST = os.environ.get("CODEX_FAST_MODEL", "gpt-6-luna")
PREAMBLE = ("Use $imagegen to generate exactly one image with the built-in image tool "
            "(do not use the CLI or API fallback). Reply with the absolute path of the saved image file only.\n\n")
EXTS = (".png", ".jpg", ".jpeg", ".webp")


def free_name(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem}-v{n}{ext}"):
        n += 1
    return f"{stem}-v{n}{ext}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--model", default="fast")
    ap.add_argument("--prompt-file")
    ap.add_argument("prompt", nargs="?")
    a = ap.parse_args()

    if a.prompt_file:
        prompt = open(a.prompt_file).read()
    elif a.prompt and a.prompt != "-":
        prompt = a.prompt
    else:
        prompt = sys.stdin.read()
    if not prompt.strip():
        sys.exit("codex-image: empty prompt")

    model = FAST if a.model in ("fast", "luna") else a.model
    tmp = tempfile.mkdtemp(prefix="codex-image-")
    last = os.path.join(tmp, "last.txt")
    cmd = ["codex", "exec", "-m", model, "-s", "workspace-write", "--skip-git-repo-check",
           "--ephemeral", "--disable", "multi_agent", "-o", last]
    for r in a.ref:
        cmd += ["-i", os.path.abspath(r)]
    t0 = time.time()
    with open(os.path.join(tmp, "stdout.txt"), "w") as out, open(os.path.join(tmp, "stderr.txt"), "w") as err:
        rc = subprocess.run(cmd + [PREAMBLE + prompt], stdin=subprocess.DEVNULL, stdout=out, stderr=err).returncode

    # the reply should be one path; fall back to the newest image Codex wrote during this run
    found = None
    if os.path.exists(last):
        for line in open(last).read().splitlines():
            p = os.path.expanduser(line.strip().strip("`'\""))
            if p.lower().endswith(EXTS) and os.path.isfile(p):
                found = p
                break
    if not found:
        new = [p for p in glob.glob(os.path.expanduser("~/.codex/generated_images/**/*"), recursive=True)
               if p.lower().endswith(EXTS) and os.path.getmtime(p) >= t0]
        found = max(new, key=os.path.getmtime) if new else None
    if not found:
        print("codex-image: no image produced.", open(os.path.join(tmp, "stderr.txt")).read()[-1500:], sep="\n")
        sys.exit(rc or 1)

    dest = free_name(os.path.abspath(os.path.expanduser(a.out)))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(found, dest)
    print(f"[codex-image] model={model} refs={len(a.ref)} time={time.time()-t0:.0f}s logs={tmp}")
    print(dest)


main()
