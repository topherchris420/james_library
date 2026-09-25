extends RefCounted
class_name ToneReader

## Presentation-only mood guess for an utterance, used when the backend sends no
## tone or "neutral". It never changes what an agent says; it only picks which
## expression the avatar wears while saying it. Order matters: the first rule
## that matches wins, questions outrank analytical wording, and neutral is the default.

const RULES: Array = [
	["skeptical", ["not convinced", "i doubt", "doubtful", "unlikely", "implausible", "not plausible",
		"hand-waving", "hand waving", "questionable", "that's wrong", "i disagree", "can't be built",
		"cannot be built", "where's the", "show me the", "reality check", "prove it"]],
	["concerned", ["worried", "concern", "risk", "danger", "unsafe", "fail", "problem", "careful",
		"limitation", "decoheren"]],
	["excited", ["brilliant", "beautiful", "amazing", "exciting", "fascinating", "love this",
		"incredible", "breakthrough", "wow", "elegant"]],
	["pleased", ["agreed", "i agree", "exactly", "good point", "fair point", "well said", "yes,",
		"nice", "great", "that works", "makes sense"]],
]
const FOCUSED_MARKERS: Array = ["measure", "calculate", "equation", "verify", "test", "data", "specifically",
	"precisely", "tolerance", "budget", "constraint", "bound"]


static func infer(text: String) -> String:
	var lowered := " %s " % text.to_lower()
	for rule in RULES:
		for marker in rule[1]:
			if lowered.contains(str(marker)):
				return str(rule[0])
	var trimmed := text.strip_edges()
	if trimmed.ends_with("?") or trimmed.count("?") >= 2:
		return "curious"
	if trimmed.ends_with("!"):
		return "excited"
	for marker in FOCUSED_MARKERS:
		if lowered.contains(str(marker)):
			return "focused"
	return "neutral"
