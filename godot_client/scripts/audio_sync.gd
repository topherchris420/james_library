extends Node
class_name AudioSync

signal utterance_started(agent_id: String)
signal utterance_finished(agent_id: String)

## Voice playback runs on its own bus so its level can be metered for lip-sync.
const VOICE_BUS := "RainVoice"
## Peak level (dB) mapped to a closed and a fully open mouth.
const LEVEL_FLOOR_DB := -46.0
const LEVEL_CEIL_DB := -8.0

@export var fallback_seconds_per_word: float = 0.28
@export var ducking_attack_s: float = 0.08
@export var ducking_release_s: float = 0.22

var _voice_player: AudioStreamPlayer
var _ambient_player: AudioStreamPlayer

var _active_agent_id: String = ""
var _using_synthetic_voice: bool = false
var _voice_generator: AudioStreamGenerator
var _voice_playback: AudioStreamGeneratorPlayback
var _voice_phase: float = 0.0
var _voice_time_left: float = 0.0
var _voice_base_hz: float = 190.0
var _voice_wobble_hz: float = 12.0
var _voice_gain: float = 0.06
var _voice_elapsed: float = 0.0
var _voice_bus_idx: int = -1
var _voice_level_seen: bool = false
## Synthetic babble: one (start_s, end_s, pitch multiplier) entry per syllable.
var _syllables: Array[Vector3] = []
var _syllable_cursor: int = 0
var _level_cursor: int = 0
var _osc_phase: float = 0.0

var _ambient_generator: AudioStreamGenerator
var _ambient_playback: AudioStreamGeneratorPlayback
var _ambient_phase: float = 0.0
var _ambient_base_hz: float = 120.0
var _ambient_wobble_hz: float = 0.2
var _ambient_gain: float = 0.015
var _ambient_base_volume_db: float = -25.0
var _ambient_current_volume_db: float = -25.0
var _ambient_target_volume_db: float = -25.0
var _ambient_ducking_db: float = -6.0
var _ambient_is_ducked: bool = false


func _ready() -> void:
	_voice_player = AudioStreamPlayer.new()
	_voice_player.name = "VoicePlayer"
	_voice_player.finished.connect(_on_voice_finished)
	add_child(_voice_player)
	_voice_bus_idx = _ensure_voice_bus()
	_voice_player.bus = VOICE_BUS

	_ambient_player = AudioStreamPlayer.new()
	_ambient_player.name = "AmbientPlayer"
	add_child(_ambient_player)


func _process(delta: float) -> void:
	_push_ambient_frames()
	_update_ambient_ducking(delta)
	if _active_agent_id != "":
		_voice_elapsed += delta
	if _using_synthetic_voice:
		_push_synthetic_voice_frames(delta)


## Loudness of the current utterance in 0..1 for lip-sync, or -1.0 when it cannot
## be measured (for example a file voice on a machine with no audio output).
func get_voice_level() -> float:
	if _active_agent_id == "":
		return 0.0
	if _using_synthetic_voice:
		return _syllable_envelope(_voice_elapsed, true)
	if _voice_bus_idx < 0:
		return -1.0
	var peak_db := maxf(
		AudioServer.get_bus_peak_volume_left_db(_voice_bus_idx, 0),
		AudioServer.get_bus_peak_volume_right_db(_voice_bus_idx, 0),
	)
	if peak_db <= -120.0:
		# Silence before any signal means "no meter here", not "mouth closed".
		return 0.0 if _voice_level_seen else -1.0
	_voice_level_seen = true
	return clampf((peak_db - LEVEL_FLOOR_DB) / (LEVEL_CEIL_DB - LEVEL_FLOOR_DB), 0.0, 1.0)


func apply_theme_audio(audio_cfg: Dictionary) -> void:
	var ambient_cfg: Dictionary = {}
	if audio_cfg.has("ambient") and audio_cfg["ambient"] is Dictionary:
		ambient_cfg = audio_cfg["ambient"]
	_ambient_ducking_db = float(audio_cfg.get("ducking_db", -6.0))
	ducking_attack_s = maxf(0.01, float(audio_cfg.get("ducking_attack_s", ducking_attack_s)))
	ducking_release_s = maxf(0.01, float(audio_cfg.get("ducking_release_s", ducking_release_s)))

	_start_ambient_synth(ambient_cfg)


func play_utterance(agent_id: String, audio_payload: Dictionary, text: String) -> void:
	if _active_agent_id != "":
		stop_current_utterance(true)

	_active_agent_id = agent_id
	_voice_elapsed = 0.0
	_voice_level_seen = false
	_set_ambient_ducking(true)
	emit_signal("utterance_started", _active_agent_id)

	var stream := _resolve_audio_stream(audio_payload)
	if stream != null:
		_using_synthetic_voice = false
		_voice_player.stream = stream
		_voice_player.volume_db = float(audio_payload.get("volume_db", 0.0))
		_voice_player.play()
		return

	var duration_s := _estimate_duration_seconds(audio_payload, text)
	_start_synthetic_voice(duration_s, agent_id, text)


func stop_current_utterance(emit_finished: bool = true) -> void:
	if _voice_player.playing:
		_voice_player.stop()
	_using_synthetic_voice = false
	_voice_time_left = 0.0
	_voice_playback = null
	_set_ambient_ducking(false)

	if emit_finished and _active_agent_id != "":
		var ended_agent := _active_agent_id
		_active_agent_id = ""
		emit_signal("utterance_finished", ended_agent)
	else:
		_active_agent_id = ""


func _on_voice_finished() -> void:
	_finish_active_utterance()


func _finish_active_utterance() -> void:
	if _active_agent_id == "":
		return
	var ended_agent := _active_agent_id
	_active_agent_id = ""
	_using_synthetic_voice = false
	_voice_time_left = 0.0
	_voice_playback = null
	_set_ambient_ducking(false)
	if _voice_player.playing:
		_voice_player.stop()
	emit_signal("utterance_finished", ended_agent)


func _resolve_audio_stream(audio_payload: Dictionary) -> AudioStream:
	var mode := str(audio_payload.get("mode", "")).to_lower()
	var path := ""

	if mode == "file":
		path = str(audio_payload.get("path", ""))
		if path == "":
			path = str(audio_payload.get("url", ""))
	elif mode == "res":
		path = str(audio_payload.get("path", ""))
	elif mode == "url":
		# Remote URL downloads are not implemented in MVP; fallback to synthetic voice.
		return null

	if path == "":
		return null

	if path.begins_with("res://"):
		var loaded := load(path)
		if loaded is AudioStream:
			return loaded
		return null

	if path.begins_with("user://"):
		path = ProjectSettings.globalize_path(path)

	if not FileAccess.file_exists(path):
		push_warning("Voice file not found, using synthetic voice: %s" % path)
		return null

	# Files on disk are not imported resources, so decode them directly.
	var ext := path.get_extension().to_lower()
	if ext == "wav":
		return _load_wav_file(path)
	if ext == "mp3":
		var mp3 := AudioStreamMP3.new()
		mp3.data = FileAccess.get_file_as_bytes(path)
		return mp3
	if ext == "ogg":
		return AudioStreamOggVorbis.load_from_file(path)

	return null


## Decode an uncompressed PCM WAV (8 or 16 bit, mono or stereo), which is what
## the backend's TTS export writes. Godot 4.2 has no runtime WAV loader, so the
## RIFF chunks are read here. Anything else falls back to the synthetic voice.
func _load_wav_file(path: String) -> AudioStreamWAV:
	var bytes := FileAccess.get_file_as_bytes(path)
	if bytes.size() < 44 or bytes.slice(0, 4).get_string_from_ascii() != "RIFF" \
			or bytes.slice(8, 12).get_string_from_ascii() != "WAVE":
		push_warning("Not a RIFF/WAVE file, using synthetic voice: %s" % path)
		return null

	var audio_format := 0
	var channels := 0
	var mix_rate := 0
	var bits := 0
	var pcm := PackedByteArray()
	var pos := 12
	while pos + 8 <= bytes.size():
		var chunk_id := bytes.slice(pos, pos + 4).get_string_from_ascii()
		var chunk_size := bytes.decode_u32(pos + 4)
		var body := pos + 8
		if chunk_id == "fmt " and body + 16 <= bytes.size():
			audio_format = bytes.decode_u16(body)
			channels = bytes.decode_u16(body + 2)
			mix_rate = bytes.decode_u32(body + 4)
			bits = bytes.decode_u16(body + 14)
			if audio_format == 0xFFFE and chunk_size >= 26 and body + 26 <= bytes.size():
				audio_format = bytes.decode_u16(body + 24)  # WAVE_FORMAT_EXTENSIBLE sub-format
		elif chunk_id == "data":
			pcm = bytes.slice(body, mini(body + chunk_size, bytes.size()))
		pos = body + chunk_size + (chunk_size % 2)

	if audio_format != 1 or channels < 1 or channels > 2 or (bits != 8 and bits != 16) or pcm.is_empty():
		push_warning("Unsupported WAV (format %d, %d ch, %d bit), using synthetic voice: %s" % [audio_format, channels, bits, path])
		return null

	var stream := AudioStreamWAV.new()
	stream.mix_rate = mix_rate
	stream.stereo = channels == 2
	if bits == 16:
		stream.format = AudioStreamWAV.FORMAT_16_BITS
	else:
		stream.format = AudioStreamWAV.FORMAT_8_BITS
		for i in pcm.size():
			pcm[i] = pcm[i] ^ 0x80  # WAV stores unsigned 8-bit; Godot expects signed
	stream.data = pcm
	return stream


func _estimate_duration_seconds(audio_payload: Dictionary, text: String) -> float:
	if audio_payload.has("duration_ms"):
		return maxf(0.4, float(audio_payload["duration_ms"]) / 1000.0)
	if audio_payload.has("duration_s"):
		return maxf(0.4, float(audio_payload["duration_s"]))

	var words := maxi(1, text.split(" ", false).size())
	return maxf(0.8, float(words) * fallback_seconds_per_word)


func _ensure_voice_bus() -> int:
	var idx := AudioServer.get_bus_index(VOICE_BUS)
	if idx == -1:
		AudioServer.add_bus()
		idx = AudioServer.bus_count - 1
		AudioServer.set_bus_name(idx, VOICE_BUS)
		AudioServer.set_bus_send(idx, "Master")
	return idx


## Lay out syllables for the line: word lengths set syllable counts, spaces and
## punctuation add pauses, and the whole schedule is stretched to the duration.
func _build_syllables(duration_s: float, agent_id: String, text: String) -> void:
	_syllables.clear()
	_syllable_cursor = 0
	_level_cursor = 0
	var rng := RandomNumberGenerator.new()
	rng.seed = hash(agent_id + "|" + text)
	var words := text.split(" ", false)
	if words.is_empty():
		words = PackedStringArray(["..."])
	var t := 0.04
	for word in words:
		var letters := word.length()
		var count := clampi(int(ceil(float(letters) / 3.2)), 1, 4)
		for i in count:
			var length := rng.randf_range(0.085, 0.16)
			_syllables.append(Vector3(t, t + length, rng.randf_range(0.88, 1.18)))
			t += length + rng.randf_range(0.012, 0.035)
		t += rng.randf_range(0.05, 0.12)
		if word.ends_with(",") or word.ends_with(";") or word.ends_with(":"):
			t += rng.randf_range(0.12, 0.2)
		elif word.ends_with(".") or word.ends_with("?") or word.ends_with("!"):
			t += rng.randf_range(0.22, 0.34)
	var stretch := duration_s / maxf(0.1, t)
	for i in _syllables.size():
		var s := _syllables[i]
		_syllables[i] = Vector3(s.x * stretch, s.y * stretch, s.z)


## Trapezoid loudness of the syllable under ``t`` (0 between syllables). Two
## cursors keep lookups O(1) for the audio thread feed and the lip-sync reader.
func _syllable_envelope(t: float, for_level: bool) -> float:
	var cursor := _level_cursor if for_level else _syllable_cursor
	while cursor < _syllables.size() and _syllables[cursor].y < t:
		cursor += 1
	if for_level:
		_level_cursor = cursor
	else:
		_syllable_cursor = cursor
	if cursor >= _syllables.size():
		return 0.0
	var s := _syllables[cursor]
	if t < s.x:
		return 0.0
	var p := (t - s.x) / maxf(0.001, s.y - s.x)
	return clampf(minf(p / 0.2, (1.0 - p) / 0.3), 0.0, 1.0)


func _syllable_pitch(t: float) -> float:
	if _syllable_cursor < _syllables.size():
		var s := _syllables[_syllable_cursor]
		var p := clampf((t - s.x) / maxf(0.001, s.y - s.x), 0.0, 1.0)
		return s.z * (1.0 - 0.06 * p)
	return 1.0


func _start_synthetic_voice(duration_s: float, agent_id: String, text: String = "") -> void:
	_voice_generator = AudioStreamGenerator.new()
	_voice_generator.mix_rate = 22050.0
	_voice_generator.buffer_length = 0.25
	_voice_player.stream = _voice_generator
	_voice_player.volume_db = -7.0
	_voice_player.play()

	_voice_playback = _voice_player.get_stream_playback() as AudioStreamGeneratorPlayback
	_voice_phase = 0.0
	_voice_time_left = duration_s
	_using_synthetic_voice = true

	var pitch_seed := float(abs(hash(agent_id)) % 80)
	_voice_base_hz = 170.0 + pitch_seed
	_voice_wobble_hz = 8.0 + float(abs(hash(agent_id + "_wob")) % 10)
	_build_syllables(duration_s, agent_id, text)


func _push_synthetic_voice_frames(delta: float) -> void:
	if _voice_generator == null:
		_finish_active_utterance()
		return
	if _voice_playback == null:
		_voice_playback = _voice_player.get_stream_playback() as AudioStreamGeneratorPlayback
		if _voice_playback == null:
			return

	_voice_time_left -= delta
	if _voice_time_left <= 0.0:
		_finish_active_utterance()
		return

	# Retro babble: a 25% pulse wave blended with a sine, gated by the syllable
	# schedule, so the sound and the avatar's mouth share one rhythm.
	var frames := _voice_playback.get_frames_available()
	var mix_rate := _voice_generator.mix_rate
	for i in range(frames):
		var t := _voice_phase / mix_rate
		var envelope := _syllable_envelope(t, false)
		var sample := 0.0
		var wobble := sin(TAU * _voice_wobble_hz * t) * 0.04
		_osc_phase = fmod(_osc_phase + _voice_base_hz * _syllable_pitch(t) * (1.0 + wobble) / mix_rate, 1.0)
		if envelope > 0.0:
			var pulse := 1.0 if _osc_phase < 0.25 else -0.33
			var sine := sin(TAU * _osc_phase)
			sample = (0.55 * pulse + 0.45 * sine) * envelope * _voice_gain
		_voice_playback.push_frame(Vector2(sample, sample))
		_voice_phase += 1.0


func _start_ambient_synth(ambient_cfg: Dictionary) -> void:
	_ambient_base_hz = float(ambient_cfg.get("base_hz", 120.0))
	_ambient_wobble_hz = float(ambient_cfg.get("wobble_hz", 0.2))
	_ambient_gain = float(ambient_cfg.get("gain", 0.015))
	_ambient_base_volume_db = float(ambient_cfg.get("volume_db", -25.0))

	_ambient_generator = AudioStreamGenerator.new()
	_ambient_generator.mix_rate = 22050.0
	_ambient_generator.buffer_length = 0.5

	_ambient_player.stream = _ambient_generator
	_ambient_current_volume_db = _ambient_base_volume_db
	_ambient_target_volume_db = _ambient_base_volume_db
	_ambient_player.volume_db = _ambient_current_volume_db
	_ambient_player.play()
	_ambient_playback = _ambient_player.get_stream_playback() as AudioStreamGeneratorPlayback
	_ambient_phase = 0.0


func _push_ambient_frames() -> void:
	if _ambient_generator == null:
		return
	if _ambient_playback == null:
		_ambient_playback = _ambient_player.get_stream_playback() as AudioStreamGeneratorPlayback
		if _ambient_playback == null:
			return

	var frames := _ambient_playback.get_frames_available()
	var mix_rate := _ambient_generator.mix_rate
	for i in range(frames):
		var t := _ambient_phase / mix_rate
		var mod := sin(TAU * _ambient_wobble_hz * t) * 0.25
		var sample := sin(TAU * _ambient_base_hz * (1.0 + mod) * t) * _ambient_gain
		_ambient_playback.push_frame(Vector2(sample, sample))
		_ambient_phase += 1.0


func _set_ambient_ducking(active: bool) -> void:
	_ambient_is_ducked = active
	if _ambient_is_ducked:
		_ambient_target_volume_db = _ambient_base_volume_db + _ambient_ducking_db
	else:
		_ambient_target_volume_db = _ambient_base_volume_db


func _update_ambient_ducking(delta: float) -> void:
	if _ambient_player == null:
		return

	var target := _ambient_target_volume_db
	var current := _ambient_player.volume_db
	if is_equal_approx(current, target):
		return

	var step_alpha := 0.0
	if target < current:
		step_alpha = clampf(delta / ducking_attack_s, 0.0, 1.0)
	else:
		step_alpha = clampf(delta / ducking_release_s, 0.0, 1.0)

	_ambient_current_volume_db = lerpf(current, target, step_alpha)
	if absf(_ambient_current_volume_db - target) <= 0.05:
		_ambient_current_volume_db = target
	_ambient_player.volume_db = _ambient_current_volume_db
