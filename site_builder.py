"""Build and check the static course site. Standard library only."""
import html, json, re
from pathlib import Path

E = html.escape


def md_to_html(md):
    """Small Markdown converter for what lesson text actually uses: ## / ### headings, paragraphs,
    - and 1. lists, **bold**, *italic*, `code` and fenced code blocks."""
    out, para, lst, code = [], [], None, None

    def inline(t):
        t = E(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
        return t

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para))); para = []
        if lst:
            tag, items = lst
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(i) for i in items), tag)); lst = None

    for line in md.splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                out.append("<pre><code>%s</code></pre>" % E("\n".join(code))); code = None
            else:
                code.append(line)
            continue
        s = line.strip()
        if s.startswith("```"):
            flush(); code = []; continue
        m = re.match(r"^(#{2,4})\s+(.*)", s)
        if m:
            flush(); lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl)); continue
        m = re.match(r"^[-*]\s+(.*)", s) or re.match(r"^\d+[.)]\s+(.*)", s)
        if m:
            tag = "ol" if re.match(r"^\d", s) else "ul"
            if para: flush()
            if lst and lst[0] != tag: flush()
            lst = lst or (tag, [])
            lst[1].append(m.group(1)); continue
        if not s:
            flush(); continue
        if lst: flush()
        para.append(s)
    flush()
    if code is not None:
        out.append("<pre><code>%s</code></pre>" % E("\n".join(code)))
    return "\n".join(out)


CSS = """:root { --ink:#1d1a16; --soft:#5d564c; --paper:#fbf8f3; --card:#ffffff; --line:#e6dfd4; --accent:%(accent)s; }
@media (prefers-color-scheme: dark) { :root { --ink:#efe9df; --soft:#b3aa9c; --paper:#16140f; --card:#1f1c16; --line:#36312a; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 18px/1.65 Charter, "Iowan Old Style", Georgia, serif; }
.wrap { max-width: 44rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
h1, h2, h3, .label, .btn, nav, .meta { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 2.4rem; line-height: 1.15; margin: .3em 0 .3em; text-wrap: balance; }
h2 { font-size: 1.35rem; margin: 2.2em 0 .5em; }
h3 { font-size: 1.1rem; margin: 1.6em 0 .4em; }
a { color: var(--accent); }
.label { font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; color: var(--soft); }
.lead { font-size: 1.2rem; color: var(--soft); }
.btn { display: inline-block; background: var(--accent); color: #fff; text-decoration: none; padding: .7em 1.3em; border-radius: 6px; font-weight: 600; }
.btn.ghost { background: transparent; color: var(--accent); border: 1.5px solid var(--accent); margin-left: .5em; }
.syllabus { list-style: none; padding: 0; counter-reset: l; }
.syllabus li { counter-increment: l; border-top: 1px solid var(--line); padding: .9em 0 .9em 3rem; position: relative; }
.syllabus li::before { content: counter(l, decimal-leading-zero); position: absolute; left: 0; top: .9em; font: 600 1rem system-ui, sans-serif; color: var(--accent); }
.syllabus a { font: 600 1.05rem system-ui, sans-serif; text-decoration: none; }
.syllabus p { margin: .2em 0 0; color: var(--soft); font-size: .95rem; }
details { border-top: 1px solid var(--line); padding: .8em 0; }
summary { cursor: pointer; font: 600 1rem system-ui, sans-serif; }
pre { background: var(--card); border: 1px solid var(--line); padding: 1em; overflow-x: auto; border-radius: 6px; font-size: .85rem; }
code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .9em; }
nav.top { font-size: .9rem; margin-bottom: 1.5rem; }
.meta { color: var(--soft); font-size: .95rem; }
.quiz { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 1.2rem 1.4rem; margin-top: 2.5rem; }
.quiz fieldset { border: 0; padding: 0; margin: 0 0 1.2rem; }
.quiz legend { font: 600 1rem system-ui, sans-serif; margin-bottom: .4em; }
.quiz label { display: block; padding: .25em 0; cursor: pointer; }
.quiz .why { display: none; font-size: .92rem; margin: .3em 0 0; }
.quiz .right .why, .quiz .wrong .why { display: block; }
.quiz .right legend::after { content: "  ✓"; color: #2f8a3e; }
.quiz .wrong legend::after { content: "  ✗"; color: #b3261e; }
.pager { display: flex; justify-content: space-between; gap: 1rem; margin-top: 3rem; font: 600 .95rem system-ui, sans-serif; }
footer { margin-top: 4rem; font-size: .85rem; color: var(--soft); }
a:focus-visible, button:focus-visible, summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
"""

QUIZ_JS = """<script>
document.querySelectorAll('form.quiz').forEach(f => f.addEventListener('submit', e => {
  e.preventDefault(); let n = 0;
  f.querySelectorAll('fieldset').forEach(fs => {
    const pick = fs.querySelector('input:checked'); fs.classList.remove('right', 'wrong');
    if (!pick) return;
    const ok = pick.value === fs.dataset.answer; if (ok) n++;
    fs.classList.add(ok ? 'right' : 'wrong');
  });
  f.querySelector('.score').textContent = n + ' of ' + f.querySelectorAll('fieldset').length + ' correct';
}));
</script>"""

DECK = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s - slides</title><style>
:root { --accent:%(accent)s; } * { box-sizing: border-box; }
html, body { margin: 0; height: 100%%; background: #14120e; color: #f4efe6; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.s { position: absolute; inset: 0; display: none; flex-direction: column; justify-content: center; padding: 6vh 8vw; }
.s.on { display: flex; } .s h2 { font-size: clamp(1.6rem, 4.5vw, 3.2rem); margin: 0 0 .6em; line-height: 1.15; }
.s ul { font-size: clamp(1.05rem, 2.4vw, 1.7rem); line-height: 1.5; padding-left: 1.1em; } .s li { margin: .35em 0; }
.s.cover h2 { font-size: clamp(2rem, 6vw, 4.2rem); } .kicker { color: var(--accent); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: .95rem; }
.bar { position: fixed; left: 0; bottom: 0; height: 4px; background: var(--accent); transition: width .2s; }
.ui { position: fixed; right: 1.2rem; bottom: 1rem; font-size: .85rem; color: #b9b1a3; } .ui a { color: #b9b1a3; }
</style></head><body>
%(slides)s
<div class="bar" id="bar"></div><div class="ui"><span id="n"></span> · <a href="../lessons/%(num)s.html">back to the lesson</a> · arrows / tap</div>
<script>
const S = [...document.querySelectorAll('.s')]; let i = 0;
const show = k => { i = Math.max(0, Math.min(S.length - 1, k)); S.forEach((s, j) => s.classList.toggle('on', j === i));
  document.getElementById('n').textContent = (i + 1) + ' / ' + S.length; document.getElementById('bar').style.width = ((i + 1) / S.length * 100) + '%%'; };
addEventListener('keydown', e => { if (['ArrowRight', 'ArrowDown', ' ', 'PageDown'].includes(e.key)) show(i + 1); if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) show(i - 1); });
addEventListener('click', e => { if (e.target.closest('a')) return; show(e.clientX > innerWidth / 3 ? i + 1 : i - 1); });
show(0);
</script></body></html>"""


def page(title, body, css="style.css"):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><link rel="stylesheet" href="%s"></head><body><div class="wrap">%s'
            '<footer>Made with course-forge.</footer></div></body></html>' % (E(title), css, body))


def build(st, site, cta_url="#enroll", accent="#c2410c"):
    o, L = st["outline"], st["landing"]
    site = Path(site)
    (site / "lessons").mkdir(parents=True, exist_ok=True)
    (site / "slides").mkdir(parents=True, exist_ok=True)
    (site / "style.css").write_text(CSS % {"accent": accent}, encoding="utf-8")
    n = len(o["lessons"])
    syl = "".join('<li><a href="lessons/%02d.html">%s</a><p>%s</p></li>' % (i + 1, E(l["title"]), E(l["goal"]))
                  for i, l in enumerate(o["lessons"]))
    faq = "".join("<details><summary>%s</summary><p>%s</p></details>" % (E(f["q"]), E(f["a"])) for f in L["faq"])
    body = ('<p class="label">%s · %d lessons</p><h1>%s</h1><p class="lead">%s</p>'
            '<p><a class="btn" id="enroll" href="%s">Enroll</a><a class="btn ghost" href="#syllabus">See the lessons</a></p>'
            '<h2>What you will be able to do</h2><ul>%s</ul>'
            '<h2>Who it is for</h2><ul>%s</ul>'
            '<h2 id="syllabus">The lessons</h2><ol class="syllabus">%s</ol>'
            '<p class="meta"><strong>Before you start:</strong> %s</p>'
            '<h2>Questions</h2>%s') % (
        E(o["title"]), n, E(L["headline"]), E(L["subhead"]), E(cta_url),
        "".join("<li>%s</li>" % E(x) for x in o["outcomes"]),
        "".join("<li>%s</li>" % E(x) for x in L["for_who"]), syl, E(o.get("prerequisites", "")), faq)
    (site / "index.html").write_text(page(o["title"], body), encoding="utf-8")

    for i, l in enumerate(o["lessons"]):
        k, num = str(i), "%02d" % (i + 1)
        qs = st["quizzes"][k]["questions"]
        quiz = '<form class="quiz"><p class="label">Check yourself</p>' + "".join(
            '<fieldset data-answer="%d"><legend>%d. %s</legend>%s<p class="why">%s</p></fieldset>' % (
                q["answer"], j + 1, E(q["q"]),
                "".join('<label><input type="radio" name="q%d" value="%d"> %s</label>' % (j, oi, E(opt))
                        for oi, opt in enumerate(q["options"])), E(q["why"]))
            for j, q in enumerate(qs)) + '<button class="btn" type="submit">Check answers</button> <span class="score meta"></span></form>'
        prev = '<a href="%02d.html">← %s</a>' % (i, E(o["lessons"][i - 1]["title"])) if i else '<a href="../index.html">← Course home</a>'
        nxt = '<a href="%02d.html">%s →</a>' % (i + 2, E(o["lessons"][i + 1]["title"])) if i + 1 < n else '<a href="../index.html">Course home →</a>'
        body = ('<nav class="top"><a href="../index.html">%s</a></nav><p class="label">Lesson %d of %d</p><h1>%s</h1>'
                '<p class="lead">%s</p><p class="meta"><a href="../slides/%s.html">Open the slides</a></p>%s%s%s'
                '<div class="pager">%s%s</div>') % (
            E(o["title"]), i + 1, n, E(l["title"]), E(l["goal"]), num, md_to_html(st["lessons"][k]), quiz, QUIZ_JS, prev, nxt)
        (site / "lessons" / (num + ".html")).write_text(page(l["title"] + " - " + o["title"], body, css="../style.css"), encoding="utf-8")

        sl = st["slides"][k]["slides"]
        slides = '<section class="s cover"><p class="kicker">Lesson %d of %d</p><h2>%s</h2><p>%s</p></section>' % (
            i + 1, n, E(l["title"]), E(l["goal"]))
        slides += "".join('<section class="s"><h2>%s</h2><ul>%s</ul></section>' % (
            E(s["title"]), "".join("<li>%s</li>" % E(b) for b in s["bullets"])) for s in sl)
        (site / "slides" / (num + ".html")).write_text(DECK % {"title": E(l["title"]), "accent": accent, "slides": slides, "num": num},
                                                       encoding="utf-8")


def check(site):
    """Every internal link resolves, nothing loads from another server, every lesson has its quiz."""
    site, problems = Path(site), []
    pages = list(site.rglob("*.html"))
    for p in pages:
        t = p.read_text(encoding="utf-8")
        for ref in re.findall(r'src="(https?://[^"]+)"', t):
            problems.append("%s loads %s from another server" % (p.name, ref))
        for ref in re.findall(r'(?:href|src)="([^"]+)"', t):
            if ref.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = (p.parent / ref.split("#")[0]).resolve()
            if not target.exists():
                problems.append("%s links to missing %s" % (p.relative_to(site), ref))
    for p in (site / "lessons").glob("*.html"):
        if p.read_text(encoding="utf-8").count("<fieldset") != 4:
            problems.append("%s does not have 4 quiz questions" % p.name)
    return sorted(set(problems))


def manuscript(st):
    o = st["outline"]
    out = ["# %s" % o["title"], "", "_%s_" % o["subtitle"], "", "## Outcomes", ""]
    out += ["- %s" % x for x in o["outcomes"]] + [""]
    for i, l in enumerate(o["lessons"]):
        k = str(i)
        out += ["", "---", "", "## Lesson %d: %s" % (i + 1, l["title"]), "", "_%s_" % l["goal"], "", st["lessons"][k], "", "### Quiz", ""]
        for j, q in enumerate(st["quizzes"][k]["questions"], 1):
            out.append("%d. %s" % (j, q["q"]))
            out += ["   - %s%s" % (opt, "  **(answer)**" if oi == q["answer"] else "") for oi, opt in enumerate(q["options"])]
            out.append("   - _%s_" % q["why"])
    return "\n".join(out) + "\n"
