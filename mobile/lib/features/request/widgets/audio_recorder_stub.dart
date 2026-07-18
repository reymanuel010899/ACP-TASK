import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/theme/app_typography.dart';

/// A UI-ONLY audio-capture stub. It shows the record button, an animated
/// waveform, and a running timer — but records nothing and does no
/// transcription. On stop it hands back a sample description so the flow
/// continues, exactly as the mock-first scope specifies. Real recording +
/// speech-to-text is deferred to phase 2 (see README).
class AudioRecorderStub extends StatefulWidget {
  const AudioRecorderStub({required this.onTranscribed, super.key});

  /// Called with sample text when the user stops "recording".
  final ValueChanged<String> onTranscribed;

  static const _sampleTranscript =
      'Genera un template Terraform con 2 contenedores detrás de un ALB, '
      'con health checks y auto-scaling.';

  @override
  State<AudioRecorderStub> createState() => _AudioRecorderStubState();
}

class _AudioRecorderStubState extends State<AudioRecorderStub>
    with SingleTickerProviderStateMixin {
  late final AnimationController _wave;
  Timer? _timer;
  Duration _elapsed = Duration.zero;
  bool _recording = false;

  @override
  void initState() {
    super.initState();
    _wave = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
  }

  @override
  void dispose() {
    _wave.dispose();
    _timer?.cancel();
    super.dispose();
  }

  void _toggle() {
    if (_recording) {
      _stop();
    } else {
      _start();
    }
  }

  void _start() {
    setState(() {
      _recording = true;
      _elapsed = Duration.zero;
    });
    _wave.repeat();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() => _elapsed += const Duration(seconds: 1));
    });
  }

  void _stop() {
    _timer?.cancel();
    _wave.stop();
    setState(() => _recording = false);
    widget.onTranscribed(AudioRecorderStub._sampleTranscript);
  }

  String get _timeLabel {
    final m = _elapsed.inMinutes.remainder(60).toString().padLeft(1, '0');
    final s = _elapsed.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.xl,
      ),
      decoration: BoxDecoration(
        color: tokens.input,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(
          color: _recording ? tokens.accentPink : tokens.borderSubtle,
        ),
      ),
      child: Column(
        children: [
          GestureDetector(
            onTap: _toggle,
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [tokens.accentPurple, tokens.accentPink],
                ),
                shape: BoxShape.circle,
              ),
              child: Icon(
                _recording ? Icons.stop : Icons.mic,
                color: Colors.white,
                size: 28,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            height: 40,
            child: AnimatedBuilder(
              animation: _wave,
              builder: (context, _) => CustomPaint(
                size: const Size(double.infinity, 40),
                painter: _WaveformPainter(
                  phase: _wave.value,
                  active: _recording,
                  color: tokens.accentPink,
                  idle: tokens.borderSubtle,
                ),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            _timeLabel,
            style: AppTypography.mono(fontSize: 20, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            _recording ? 'Toca para detener' : 'Toca para grabar',
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: tokens.textMuted),
          ),
        ],
      ),
    );
  }
}

class _WaveformPainter extends CustomPainter {
  _WaveformPainter({
    required this.phase,
    required this.active,
    required this.color,
    required this.idle,
  });

  final double phase;
  final bool active;
  final Color color;
  final Color idle;

  @override
  void paint(Canvas canvas, Size size) {
    const barCount = 40;
    final barWidth = size.width / (barCount * 1.6);
    final paint = Paint()
      ..color = active ? color : idle
      ..strokeCap = StrokeCap.round
      ..strokeWidth = barWidth;
    final mid = size.height / 2;

    for (var i = 0; i < barCount; i++) {
      final t = i / barCount;
      // A moving pseudo-random amplitude when active; flat when idle.
      final amp = active
          ? (0.2 +
                  0.8 *
                      (0.5 +
                          0.5 *
                              math.sin((t * 12) + phase * 2 * math.pi) *
                              math.cos(t * 7 + phase))) *
              (size.height / 2)
          : size.height * 0.06;
      final x = i * (size.width / barCount) + barWidth;
      canvas.drawLine(Offset(x, mid - amp), Offset(x, mid + amp), paint);
    }
  }

  @override
  bool shouldRepaint(_WaveformPainter old) =>
      old.phase != phase || old.active != active;
}
