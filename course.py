#!/usr/bin/env python3
"""course-forge: one topic in, a complete online course out.

  python course.py "Sourdough bread for beginners" --audience "home bakers" --lessons 6

Writes courses/<slug>/site/ - a landing page, one page per lesson with an interactive quiz, a
slide deck per lesson - plus course.md, the whole manuscript in one file. Every stage is checked
(lesson length and structure, quiz answers in range, every link resolving) and re-asked with the
exact problem when it fails. Interrupted runs resume where they stopped.

Any OpenAI-compatible endpoint: Ollama by default, or llama.cpp, LM Studio, vLLM, a hosted API.
"""
import argparse, html, json, os, re, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import site_builder


def chat(args, prompt, temperature=0.5):
    body = {"model": args.model, "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature, "stream": False}
    req = urllib.request.Request(args.endpoint.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + args.api_key} if args.api_key else {})})
    with urllib.request.urlopen(req, timeout=args.timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def ask(args, prompt, check, as_json=True, tries=3, label=""):
    """Ask, validate, and re-ask with the exact problems until it passes."""
    msg, problems = prompt, ["not attempted"]
    for attempt in range(1, tries + 1):
        reply = chat(args, msg)
        try:
            value = parse_json(reply) if as_json else reply.strip()
            problems = check(value)
        except Exception as e:
            value, problems = None, ["the reply was not valid JSON (%s)" % str(e)[:80]]
        print("    %s attempt %d: %s" % (label, attempt, "ok" if not problems else "; ".join(problems[:2])), flush=True)
        if not problems:
            return value
        msg = (prompt + "\n\nYour previous answer had these problems:\n- " + "\n- ".join(problems)
               + "\nFix all of them and answer again in the same format.")
    raise RuntimeError("%s failed after %d tries: %s" % (label, tries, problems))


# ---- prompts and checks -------------------------------------------------------------------
def outline_prompt(a):
    return ("Design a short online course.\nTopic: %s\nAudience: %s\nNumber of lessons: %d\n\n"
            "Reply with JSON only:\n"
            '{"title": "<course title>", "subtitle": "<one plain sentence: what the learner can do after>", '
            '"outcomes": ["<4 to 6 concrete things the learner can do afterwards>"], '
            '"prerequisites": "<one line>", '
            '"lessons": [{"title": "<lesson title>", "goal": "<one sentence>", "key_points": ["<3 to 5 points>"]}]}\n'
            "Order the lessons so each builds on the last. No hype, no income claims." % (a.topic, a.audience, a.lessons))


def check_outline(o, n):
    p = []
    if not o.get("title"): p.append("missing title")
    if not 4 <= len(o.get("outcomes", [])) <= 6: p.append("outcomes must have 4 to 6 items")
    ls = o.get("lessons", [])
    if len(ls) != n: p.append("there must be exactly %d lessons, not %d" % (n, len(ls)))
    for i, l in enumerate(ls, 1):
        if not l.get("title") or not l.get("goal"): p.append("lesson %d is missing a title or goal" % i)
        if not 3 <= len(l.get("key_points", [])) <= 5: p.append("lesson %d needs 3 to 5 key points" % i)
    return p


def lesson_prompt(o, i, a):
    l = o["lessons"][i]
    prev = "; ".join(x["title"] for x in o["lessons"][:i]) or "none, this is the first lesson"
    return ("Write lesson %d of %d of the course \"%s\" for %s.\nLesson title: %s\nGoal: %s\nCover: %s\n"
            "Earlier lessons: %s\n\n"
            "Write it in Markdown, 700 to 1000 words. Structure: a short opening paragraph that says why this "
            "matters; then 3 to 5 sections with ## headings and concrete examples; one worked example; a section "
            "headed exactly \"## Try it\" with a hands-on exercise; and a final section headed exactly "
            "\"## Recap\" with three bullet points. Do not repeat the lesson title as a heading. Plain, direct "
            "language. No filler, no hype, and no facts you are not sure of - if a detail varies, say so."
            % (i + 1, len(o["lessons"]), o["title"], a.audience, l["title"], l["goal"], "; ".join(l["key_points"]), prev))


def check_lesson(md):
    p, words = [], len(md.split())
    if words < 450: p.append("the lesson is only %d words; it must be 700 to 1000" % words)
    if words > 1500: p.append("the lesson is %d words; keep it under 1000" % words)
    if len(re.findall(r"^## ", md, re.M)) < 4: p.append("use at least 3 content sections with ## headings plus Try it and Recap")
    if not re.search(r"^## Try it", md, re.M): p.append('missing the "## Try it" section')
    if not re.search(r"^## Recap", md, re.M): p.append('missing the "## Recap" section')
    if re.search(r"^# ", md, re.M): p.append("do not use a top-level # heading")
    return p


def quiz_prompt(md):
    return ("Write a 4-question multiple-choice quiz that checks understanding of this lesson (not trivia). "
            "Reply with JSON only:\n"
            '{"questions": [{"q": "<question>", "options": ["<exactly 4 options>"], "answer": <index of the correct option, 0-3>, '
            '"why": "<one sentence explaining the right answer>"}]}\n\nLesson:\n' + md)


def check_quiz(q):
    p, qs = [], q.get("questions", [])
    if len(qs) != 4: p.append("there must be exactly 4 questions")
    for i, x in enumerate(qs, 1):
        if len(x.get("options", [])) != 4: p.append("question %d needs exactly 4 options" % i)
        if not isinstance(x.get("answer"), int) or not 0 <= x["answer"] <= 3: p.append("question %d: answer must be an index 0-3" % i)
        if not x.get("why"): p.append("question %d needs a why" % i)
        if len(set(x.get("options", []))) != len(x.get("options", [])): p.append("question %d has duplicate options" % i)
    return p


def verify_quiz(a, md, q):
    """Second opinion: answer the quiz from the lesson alone, without the key, and judge each
    explanation. A key that disagrees with the lesson, or a 'why' that contradicts its own answer,
    is the worst error a course can ship."""
    blind = [{"q": x["q"], "options": x["options"]} for x in q.get("questions", [])]
    ask_ = ("Answer this quiz using ONLY the lesson below. Then, for each question, check whether the given "
            "explanation agrees with the option marked correct.\nReply with JSON only: "
            '{"answers": [<index 0-3 for each question>], "inconsistent": [<question numbers whose explanation contradicts its marked answer>]}\n\n'
            "Quiz: %s\nMarked answers and explanations: %s\n\nLesson:\n%s"
            % (json.dumps(blind), json.dumps([{"answer": x["answer"], "why": x["why"]} for x in q["questions"]]), md))
    try:
        v = parse_json(chat(a, ask_, temperature=0.1))
    except Exception:
        return []                                   # a failed second opinion must not block the course
    p = []
    for i, (mine, key) in enumerate(zip(v.get("answers", []), [x["answer"] for x in q["questions"]]), 1):
        if mine != key:
            p.append("question %d: the answer key (%d) disagrees with what the lesson says (%s)" % (i, key, mine))
    for n in v.get("inconsistent", []) or []:
        p.append("question %s: the explanation contradicts the marked answer" % n)
    return p


def slides_prompt(title, md):
    return ("Turn this lesson into 6 to 9 presentation slides. Reply with JSON only:\n"
            '{"slides": [{"title": "<short slide title>", "bullets": ["<2 to 4 short bullets, under 12 words each>"]}]}\n\n'
            "Lesson title: %s\nLesson:\n%s" % (title, md))


def check_slides(s):
    p, ss = [], s.get("slides", [])
    if not 6 <= len(ss) <= 9: p.append("there must be 6 to 9 slides, not %d" % len(ss))
    for i, x in enumerate(ss, 1):
        if not x.get("title"): p.append("slide %d needs a title" % i)
        if not 2 <= len(x.get("bullets", [])) <= 4: p.append("slide %d needs 2 to 4 bullets" % i)
        if any(len(b.split()) > 16 for b in x.get("bullets", [])): p.append("slide %d has bullets that are too long" % i)
    return p


def landing_prompt(o, a):
    return ("Write the landing page copy for this course. Reply with JSON only:\n"
            '{"headline": "<under 10 words>", "subhead": "<one or two sentences>", '
            '"for_who": ["<3 short lines: who this is for>"], '
            '"faq": [{"q": "<question>", "a": "<answer, one to three sentences>"}]}\n'
            "Exactly 4 FAQ entries. Honest and specific: no income promises, no fake testimonials, no scarcity tricks.\n\n"
            "Course: %s\nSubtitle: %s\nAudience: %s\nOutcomes: %s\nLessons: %s"
            % (o["title"], o["subtitle"], a.audience, "; ".join(o["outcomes"]), "; ".join(l["title"] for l in o["lessons"])))


def check_landing(d):
    p = []
    for k in ("headline", "subhead"):
        if not d.get(k): p.append("missing " + k)
    if len(d.get("for_who", [])) != 3: p.append("for_who needs exactly 3 lines")
    if len(d.get("faq", [])) != 4: p.append("faq needs exactly 4 entries")
    if re.search(r"\$\d|guarantee|six figures|passive income", json.dumps(d), re.I): p.append("remove income claims and guarantees")
    return p


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:48] or "course"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic")
    ap.add_argument("--audience", default="beginners")
    ap.add_argument("--lessons", type=int, default=6)
    ap.add_argument("--out", default="courses")
    ap.add_argument("--cta-url", default="#enroll", help="where the landing page's Enroll button points (checkout, form, mailing list)")
    ap.add_argument("--accent", default="#c2410c", help="accent colour for the site")
    ap.add_argument("--endpoint", default=os.environ.get("FORGE_ENDPOINT", "http://localhost:11434/v1"))
    ap.add_argument("--model", default=os.environ.get("FORGE_MODEL", "qwen2.5:14b"))
    ap.add_argument("--api-key", default=os.environ.get("FORGE_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    root = Path(a.out) / slug(a.topic)
    root.mkdir(parents=True, exist_ok=True)
    state_f = root / "course.json"
    st = json.loads(state_f.read_text()) if state_f.exists() else {"topic": a.topic, "audience": a.audience}
    save = lambda: state_f.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    t0 = time.time()

    if "outline" not in st:
        print("outline", flush=True)
        st["outline"] = ask(a, outline_prompt(a), lambda o: check_outline(o, a.lessons), label="outline"); save()
    o = st["outline"]
    for key in ("lessons", "quizzes", "slides"):
        st.setdefault(key, {})
    for i, l in enumerate(o["lessons"]):
        k = str(i)
        print("lesson %d/%d: %s" % (i + 1, len(o["lessons"]), l["title"]), flush=True)
        if k not in st["lessons"]:
            st["lessons"][k] = ask(a, lesson_prompt(o, i, a), check_lesson, as_json=False, label="text"); save()
        if k not in st["quizzes"]:
            md_k = st["lessons"][k]
            st["quizzes"][k] = ask(a, quiz_prompt(md_k), lambda q: check_quiz(q) or verify_quiz(a, md_k, q), label="quiz"); save()
        if k not in st["slides"]:
            st["slides"][k] = ask(a, slides_prompt(l["title"], st["lessons"][k]), check_slides, label="slides"); save()
    if "landing" not in st:
        print("landing page", flush=True)
        st["landing"] = ask(a, landing_prompt(o, a), check_landing, label="landing"); save()

    site = root / "site"
    site_builder.build(st, site, cta_url=a.cta_url, accent=a.accent)
    problems = site_builder.check(site)
    (root / "course.md").write_text(site_builder.manuscript(st), encoding="utf-8")
    words = sum(len(m.split()) for m in st["lessons"].values())
    print("\n%s: %d lessons, %d words, %d quiz questions, %d slides (%.0fs)"
          % (o["title"], len(o["lessons"]), words, 4 * len(st["quizzes"]),
             sum(len(s["slides"]) for s in st["slides"].values()), time.time() - t0))
    print("site: %s/index.html  |  manuscript: %s/course.md" % (site, root))
    print("site check:", "OK" if not problems else problems)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
