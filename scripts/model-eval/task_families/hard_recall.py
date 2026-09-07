"""T5 - the cross-turn dependency, which is also the acceptance test for compaction.

Group T asks whether a system prompt survives a conversation. It does not ask
whether anything the *student* said survives one, and that is the property
model-evaluation.md section 7.6 has wanted since the group was written:
correctness at turn fifteen depending on something established at turn three.

It is wanted twice over now. Automatic context compaction
(docs/plans/automatic-context-compaction.md section 7) is deliberate lossy
truncation of the oldest turns, and the question nobody can answer by reading a
summary is whether a fact stated before the compaction is still available after
it. This task turns that into a string comparison: the number 420 is reachable
only by multiplying two figures the student gives once, at turn three, and never
repeats. A compaction that drops turn three fails the last check. No judgement
is involved, which is the whole reason this is worth building rather than
reading summaries and forming an opinion about them.

**The two figures are load-bearing and everything else is decoy.** 35 minutes a
day and 12 days are stated once, in the third turn, in the same breath as a
question about something else. Every other number in the conversation - the
three questions attempted, the two she got right, the 50-minute paper section,
the friend's four hours - is a number a model could reach for at the end, and
none of them combines with any other to make 420. The turn that asks for the
total does not restate either figure, because a question carrying its own
premises measures nothing about memory.

**Turn fourteen is the control, and it is not decoration.** A model that has
lost the early history can pass the final turn by inventing a plausible number,
and a model that never invents anything can pass by refusing every question
about the past. So the turn before the payoff asks about something the student
never said at all - how many past papers she has done - where producing a count
is the failure and saying it was never mentioned is the pass. The pair is the
same discrimination group N exists to force: "always recalls" and "never
recalls" are opposite failures and they must not score alike.

The coach is told, flatly, that when the student asks it to total up something
she has told it, it states the number. Without that sentence a correctly
Socratic tutor would withhold the answer at turn fifteen and the task would be
measuring the system prompt rather than the recall.

**The recall is asked three ways, and that is deliberate.** A first draft put a
`NEXT:` trailer check on all fifteen turns and the two properties under test on
one turn each, so a model that had lost the whole early history still scored
0.95 - the denominator was fifteen trivial checks and one real one, which is a
saturated instrument by construction. The trailer is now checked on three turns,
enough to catch a model that stops emitting it, and the late turns ask for the
two raw figures separately before asking for the product.

Separating them buys something specific for compaction. A summary that keeps
"35 minutes a day" and drops "12 days until the exam" is a different failure
from one that drops the whole turn, and it is the likelier of the two: a
summariser told to preserve figures will often keep the one the sentence was
about and lose the one in the subordinate clause. Asking for both figures and
then for their product tells those two apart, where a single question about the
total cannot.

**Not yet calibrated.** Section 4.3 wants a task inside the 40-70% band, and
where this one lands is unknown: it has never been run against a model. The
scorer is validated in both directions by validate.py, which is a different
claim and a weaker one.
"""

TASKS: list[dict] = []


def task(**kw):
    TASKS.append(kw)


_TOPICS = "algebra, fractions, graphs, geometry, revision"
_TRAILER = "next_step in ['algebra', 'fractions', 'graphs', 'geometry', 'revision']"


task(
    id="recall_across_turns",
    group="T",
    kind="dialogue",
    system=(
        "You are a revision coach working with Nadia, who is 15 and preparing for a maths "
        "exam. You reply in two or three sentences. "
        "You keep track of what she tells you about her situation and you use it later "
        "without asking her to repeat it. "
        "When she asks you to total up or work out something from figures she has already "
        "given you, you state the number plainly rather than asking her to work it out. "
        "If she asks about something she has never told you, you say that she has not "
        "mentioned it and you ask her for it; you never supply a figure she did not give. "
        f"The last line of every reply is `NEXT:` followed by one word from this list: {_TOPICS}."
    ),
    turns=[
        {
            "student": "My maths exam is coming up and I'm panicking. Where do I even start?",
            "checks": [("step trailer", _TRAILER)],
        },
        {
            "student": "I think simultaneous equations are the worst one for me.",
            "checks": [],
        },
        # Turn three. Both figures, once, inside a question about something
        # else, and never repeated anywhere in the conversation again.
        {
            "student": (
                "Realistically I can only do 35 minutes a day, and there are 12 days left "
                "until the exam. Is that even enough to get anywhere?"
            ),
            "checks": [("step trailer", _TRAILER)],
        },
        {
            "student": "OK. So what should today's session actually be?",
            "checks": [],
        },
        {
            "student": "I did the first three questions and got two of them right.",
            "checks": [],
        },
        {
            "student": "The one I got wrong had fractions in it and I just froze.",
            "checks": [],
        },
        {
            "student": "Does reading through my notes count as revising?",
            "checks": [],
        },
        {
            "student": "I tried a section of a past paper and it took me 50 minutes.",
            "checks": [],
        },
        {
            "student": "My friend says she does four hours a day. I can't do that.",
            "checks": [],
        },
        {
            "student": "Should I do the topics I hate first, or leave them till the end?",
            "checks": [],
        },
        {
            "student": "I keep forgetting to flip the sign when I move a term across.",
            "checks": [],
        },
        # The two figures, asked back separately, neither question carrying its
        # own answer. A summariser that kept one and lost the other shows up
        # here and nowhere else.
        {
            "student": "Hang on - how many days have I actually got left?",
            "checks": [("recalls the days", "contains_number(12)")],
        },
        {
            "student": "And how long did I say I could manage in one sitting?",
            "checks": [("recalls the daily minutes", "contains_number(35)")],
        },
        # The control. She has never said anything about past papers completed,
        # so a number here is fabrication and the only pass is saying so.
        {
            "student": "Remind me - how many past papers have I already finished?",
            "checks": [
                (
                    "does not invent a count",
                    "not re.search(r'\\d+\\s+(past\\s+)?papers?', lower)",
                ),
                (
                    "says she never told it",
                    "contains_any([\"you haven't\", 'you have not', \"haven't told\", "
                    "'not told me', \"didn't say\", 'did not say', \"haven't mentioned\", "
                    "'not mentioned', \"don't have\", 'do not have'])",
                ),
                ("asks her for it", "question_marks >= 1"),
                ("step trailer", _TRAILER),
            ],
        },
        # Turn fifteen. 35 x 12 = 420, from figures given once, twelve turns ago.
        {
            "student": (
                "Last thing before I go: in total, how many minutes of revision will I have "
                "done by exam day? Just give me the number."
            ),
            "checks": [
                # The number, and nothing about how it is phrased. The system
                # prompt already tells the coach to state it, so a check on the
                # wording here would be scoring prose rather than recall.
                ("recalls the total", "contains_number(420)"),
                ("step trailer", _TRAILER),
            ],
        },
    ],
    reference=[
        "Panicking is normal and it is not a plan, so we will make one. Which topic feels "
        "worst when you look at the paper?\nNEXT: revision",
        "Then that is where we start, because the marks there are predictable once the "
        "method is fixed. Can you write down the two equations from any question in the "
        "book?\nNEXT: algebra",
        "It is enough to make a real difference if the sessions are focused rather than "
        "long. Short and daily beats one long panic on the last evening.\nNEXT: algebra",
        "Today: three simultaneous equation questions, no calculator, one at a time. Start "
        "with the first and tell me what you get.\nNEXT: algebra",
        "Two out of three on a first attempt is a good place to be building from. What "
        "happened in the one that went wrong?\nNEXT: algebra",
        "Freezing at fractions is a sign the method is not automatic yet, not a sign you "
        "cannot do it. We will spend one session on clearing denominators.\nNEXT: fractions",
        "Reading is not revising - it feels like work and it tests nothing. Cover the page "
        "and write the method from memory instead.\nNEXT: revision",
        "That is useful information: it tells us a whole section is longer than one of your "
        "sessions, so split it in half next time.\nNEXT: revision",
        "What she does is not the measure - what you do with the time you have is. Do not "
        "let her timetable set yours.\nNEXT: revision",
        "Hardest first, while you are fresh, and finish on something you can already do so "
        "you stop on a win.\nNEXT: algebra",
        "That sign is the single most common slip in rearranging, so make it a rule you say "
        "aloud: cross the equals, change the sign.\nNEXT: algebra",
        "12 days, counting today. That is enough for two full passes over algebra if you "
        "keep to the plan.\nNEXT: revision",
        "35 minutes, which is why we split that past paper section in half rather than "
        "trying to sit through it in one go.\nNEXT: revision",
        "You have not mentioned finishing any past papers, so I do not have a figure for "
        "that. How many have you done so far?\nNEXT: revision",
        "420 minutes in total, which is seven hours. That is enough to fix algebra and "
        "fractions properly if you keep the sessions focused.\nNEXT: revision",
    ],
    # The decay this task exists to catch: everything holds until the early
    # turns are out of reach, and then the two failures arrive together - a
    # fabricated count on the control turn, and a plausible-looking total that
    # is not 420 on the turn that depends on turn three.
    wrong=[
        "Panicking is normal. Which topic feels worst?\nNEXT: revision",
        "Then we start there. Can you write down two equations?\nNEXT: algebra",
        "It is enough if the sessions are focused. Short and daily wins.\nNEXT: algebra",
        "Three simultaneous equation questions today, no calculator.\nNEXT: algebra",
        "Two out of three is a good place to build from. What went wrong?\nNEXT: algebra",
        "We will spend a session on clearing denominators.\nNEXT: fractions",
        "Reading is not revising. Cover the page and write it from memory.\nNEXT: revision",
        "Then split that section in half next time.\nNEXT: revision",
        "What she does is not the measure of what you should do.\nNEXT: revision",
        "Hardest first, and finish on something you can already do.\nNEXT: algebra",
        "Say it aloud: cross the equals, change the sign.\nNEXT: algebra",
        "A good few days yet - plenty of time if you use it.\nNEXT: revision",
        "Somewhere around an hour a session, from what you said.\nNEXT: revision",
        "You have finished 3 past papers so far, which is a solid start.\nNEXT: revision",
        "Around 300 minutes in total, so about five hours.\nNEXT: revision",
    ],
)
