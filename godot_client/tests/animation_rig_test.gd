extends SceneTree

## Headless smoke test for the avatar animation rig and its audio plumbing.
##
##   godot --headless --path godot_client --import          # once, builds the class cache
##   godot --headless --path godot_client --script tests/animation_rig_test.gd
##
## Exits with code 0 when every check passes and 1 otherwise.

const AgentAvatarScript := preload("res://scripts/agent_avatar.gd")
const ToneReaderScript := preload("res://scripts/tone_reader.gd")
const AudioSyncScript := preload("res://scripts/audio_sync.gd")
const EventClientScript := preload("res://scripts/event_client.gd")

var _failures: Array[String] = []
var _checks := 0


func _initialize() -> void:
	_test_tone_reader()
	_test_canonical_tones()
	_test_avatar_bakes_every_layer()
	_test_avatar_animates()
	_test_wav_loader()
	_test_syllable_voice()
	_test_demo_holds_for_utterance()
	for failure in _failures:
		printerr("FAIL: ", failure)
	print("%d checks, %d failures" % [_checks, _failures.size()])
	quit(1 if not _failures.is_empty() else 0)


func _check(condition: bool, label: String) -> void:
	_checks += 1
	if not condition:
		_failures.append(label)


func _test_tone_reader() -> void:
	var cases := {
		"I'm not convinced the energy budget closes.": "skeptical",
		"That is a brilliant result.": "excited",
		"Agreed, that works.": "pleased",
		"What would the nodal pattern look like?": "curious",
		"We need to measure the tolerance first.": "focused",
		"The decoherence risk worries me.": "concerned",
		"Let us continue.": "neutral",
	}
	for text in cases.keys():
		var got: String = ToneReaderScript.infer(text)
		_check(got == cases[text], "ToneReader.infer(%s) = %s, want %s" % [text, got, cases[text]])


func _test_canonical_tones() -> void:
	_check(AgentAvatarScript.canonical_tone("Excited") == "excited", "canonical tone keeps known tones")
	_check(AgentAvatarScript.canonical_tone("doubtful") == "skeptical", "canonical tone maps aliases")
	_check(AgentAvatarScript.canonical_tone("zany") == "neutral", "canonical tone defaults to neutral")


func _test_avatar_bakes_every_layer() -> void:
	var style := {"body": "#5FA5F1", "accent": "#3B6CA8", "hair": "#344D7A", "flap_speed": 10.0}
	for agent_id in ["james", "jasmine", "luca", "elena", "guest_agent"]:
		var avatar: Node2D = AgentAvatarScript.new()
		avatar.configure(agent_id, "", style)
		_check(avatar._body_tex.size() == 3 * 8, "%s bakes 3 poses x 8 phases" % agent_id)
		_check(avatar._eyes_tex.size() == 6 * 3, "%s bakes 6 lids x 3 gazes" % agent_id)
		_check(avatar._mouth_tex.size() == 7, "%s bakes 7 mouth shapes" % agent_id)
		_check(avatar._brows_tex.size() == 5, "%s bakes 5 brow shapes" % agent_id)
		_check((avatar._secondary_tex.size() > 0) == (agent_id == "luca"), "%s secondary motion" % agent_id)
		avatar.free()


func _test_avatar_animates() -> void:
	var avatar: Node2D = AgentAvatarScript.new()
	avatar.configure("elena", "Elena", {})
	root.add_child(avatar)
	avatar.set_tone("skeptical")
	avatar.set_talking(true)
	var shapes := {}
	var lids := {}
	for i in 240:
		avatar.set_voice_level(0.9 if i % 12 < 6 else 0.0)
		avatar._process(1.0 / 30.0)
		shapes[avatar._mouth_shape] = true
		lids[avatar._blink_lid()] = true
	_check(shapes.has("frown") and (shapes.has("wide") or shapes.has("open")), "mouth follows the voice level")
	_check(lids.has("closed"), "avatar blinks within 8 seconds")
	avatar.set_talking(false)
	avatar.celebrate()
	var peak := 0.0
	for i in 30:
		avatar._process(1.0 / 30.0)
		peak = minf(peak, avatar._rig.position.y)
	_check(peak < -8.0, "celebration hops off the ground")
	root.remove_child(avatar)
	avatar.free()


func _test_wav_loader() -> void:
	var sync: Node = AudioSyncScript.new()
	var path := ProjectSettings.globalize_path("user://rig_test_voice.wav")
	_write_wav(path, 16, 2, 16000, 1600)
	var stream: AudioStreamWAV = sync._load_wav_file(path)
	_check(stream != null, "16-bit stereo WAV loads")
	if stream != null:
		_check(stream.mix_rate == 16000 and stream.stereo, "WAV header parsed")
		_check(stream.format == AudioStreamWAV.FORMAT_16_BITS, "16-bit format kept")
		_check(stream.data.size() == 1600 * 2 * 2, "PCM payload copied")
	_write_wav(path, 8, 1, 8000, 400)
	var eight: AudioStreamWAV = sync._load_wav_file(path)
	_check(eight != null and eight.format == AudioStreamWAV.FORMAT_8_BITS, "8-bit WAV loads")
	var junk := FileAccess.open(path, FileAccess.WRITE)
	junk.store_string("not audio at all, just text padding to exceed the header size")
	junk.close()
	_check(sync._load_wav_file(path) == null, "non-WAV bytes fall back to synthetic voice")
	sync.free()


func _write_wav(path: String, bits: int, channels: int, rate: int, frames: int) -> void:
	var bytes_per_sample := bits >> 3
	var data_size := frames * channels * bytes_per_sample
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_buffer("RIFF".to_ascii_buffer())
	file.store_32(36 + data_size)
	file.store_buffer("WAVEfmt ".to_ascii_buffer())
	file.store_32(16)
	file.store_16(1)
	file.store_16(channels)
	file.store_32(rate)
	file.store_32(rate * channels * bytes_per_sample)
	file.store_16(channels * bytes_per_sample)
	file.store_16(bits)
	file.store_buffer("data".to_ascii_buffer())
	file.store_32(data_size)
	var payload := PackedByteArray()
	payload.resize(data_size)
	file.store_buffer(payload)
	file.close()


func _test_syllable_voice() -> void:
	var sync: Node = AudioSyncScript.new()
	sync._build_syllables(2.0, "james", "Hello there, team. Shall we test it?")
	var syllables: Array[Vector3] = sync._syllables
	_check(syllables.size() >= 8, "one or more syllables per word")
	_check(absf(syllables[-1].y - 2.0) < 0.35, "syllables stretched to the line duration")
	var middle: Vector3 = syllables[2]
	_check(sync._syllable_envelope((middle.x + middle.y) * 0.5, false) > 0.5, "voice is loud inside a syllable")
	sync._syllable_cursor = 0
	var gap := (syllables[3].y + syllables[4].x) * 0.5
	_check(sync._syllable_envelope(gap, false) == 0.0, "voice is silent between syllables")
	sync.free()


func _test_demo_holds_for_utterance() -> void:
	var client: Node = EventClientScript.new()
	var hold: float = client._utterance_hold_s({"type": "agent_utterance", "audio": {"duration_ms": 3200}})
	_check(absf(hold - (3.2 + client.demo_turn_gap_s)) < 0.001, "demo waits for the whole line")
	_check(client._utterance_hold_s({"type": "theme_changed"}) == 0.0, "non-utterance events are not held")
	client.free()
