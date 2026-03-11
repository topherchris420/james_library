extends Node
class_name AudioSync

signal utterance_started(agent_id: String)
signal utterance_finished(agent_id: String)

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

	_ambient_player = AudioStreamPlayer.new()
	_ambient_player.name = "AmbientPlayer"
	add_child(_ambient_player)


func _process(delta: float) -> void:
	_push_ambient_frames()
	_update_ambient_ducking(delta)
	if _using_synthetic_voice:
		_push_synthetic_voice_frames(delta)


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
	_start_synthetic_voice(duration_s, agent_id)


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

	var ext := path.get_extension().to_lower()
	if ext == "wav":
		return AudioStreamWAV.load_from_file(path)
	if ext == "mp3":
		return AudioStreamMP3.load_from_file(path)
	if ext == "ogg":
		return AudioStreamOggVorbis.load_from_file(path)

	return null


func _estimate_duration_seconds(audio_payload: Dictionary, text: String) -> float:
	if audio_payload.has("duration_ms"):
		return maxf(0.4, float(audio_payload["duration_ms"]) / 1000.0)
	if audio_payload.has("duration_s"):
		return maxf(0.4, float(audio_payload["duration_s"]))

	var words := maxi(1, text.split(" ", false).size())
	return maxf(0.8, float(words) * fallback_seconds_per_word)


func _start_synthetic_voice(duration_s: float, agent_id: String) -> void:
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

	var frames := _voice_playback.get_frames_available()
	var mix_rate := _voice_generator.mix_rate
	for i in range(frames):
		var t := _voice_phase / mix_rate
		var wobble := sin(TAU * _voice_wobble_hz * t) * 0.08
		var carrier := sin(TAU * _voice_base_hz * (1.0 + wobble) * t)
		var pulse := 0.75 + 0.25 * sin(TAU * 5.0 * t)
		var sample := carrier * pulse * _voice_gain
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
