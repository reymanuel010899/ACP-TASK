import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/router/app_router.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/app_badge.dart';
import 'package:agenttrust_mobile/core/widgets/screen_header.dart';
import 'package:agenttrust_mobile/data/fixtures/demo_fixtures.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/domain/models/task_draft.dart';
import 'package:agenttrust_mobile/features/request/widgets/audio_recorder_stub.dart';
import 'package:agenttrust_mobile/features/request/widgets/chat_panel.dart';

class TaskRequestScreen extends ConsumerStatefulWidget {
  const TaskRequestScreen({super.key});

  @override
  ConsumerState<TaskRequestScreen> createState() => _TaskRequestScreenState();
}

class _TaskRequestScreenState extends ConsumerState<TaskRequestScreen> {
  static const _capabilityId = DemoFixtures.capabilityTerraform;

  final _description = TextEditingController();
  final _budget = TextEditingController(text: '15.00');

  TaskInputMode _mode = TaskInputMode.text;
  double _minReputation = 0.70;
  int _fanOut = 3;
  bool _submitting = false;

  @override
  void dispose() {
    _description.dispose();
    _budget.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final budget = double.tryParse(_budget.text.trim()) ?? 0;
    if (_description.text.trim().isEmpty || budget <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Añade una descripción y un presupuesto válido.'),
        ),
      );
      return;
    }
    setState(() => _submitting = true);
    final draft = TaskDraft(
      capabilityId: _capabilityId,
      description: _description.text.trim(),
      budget: budget,
      currency: 'USD',
      minReputation: _minReputation,
      fanOut: _fanOut,
      inputMode: _mode,
    );
    final task =
        await ref.read(activeTaskControllerProvider.notifier).submit(draft);
    if (!mounted) return;
    setState(() => _submitting = false);
    context.push(AppRoutes.task(task.id));
  }

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final chat = ref.watch(chatScriptProvider(_capabilityId));

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            140,
          ),
          children: [
            ScreenHeader(
              title: 'Nueva Solicitud',
              trailing: AppBadge(label: 'terraform', color: tokens.accentCyan),
            ),
            const SizedBox(height: AppSpacing.lg),

            _label(context, 'Capacidad requerida'),
            const SizedBox(height: AppSpacing.sm),
            _CapabilityField(capabilityId: _capabilityId),
            const SizedBox(height: AppSpacing.lg),

            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _label(context, 'Descripción'),
                _ModeToggle(
                  mode: _mode,
                  onChanged: (m) => setState(() => _mode = m),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            if (_mode == TaskInputMode.text)
              TextField(
                controller: _description,
                maxLines: 4,
                decoration: const InputDecoration(
                  hintText:
                      'Describe la tarea, p. ej. "2 contenedores + ALB con '
                      'health checks y auto-scaling"',
                ),
              )
            else
              AudioRecorderStub(
                onTranscribed: (text) {
                  setState(() {
                    _description.text = text;
                    _mode = TaskInputMode.text;
                  });
                },
              ),
            const SizedBox(height: AppSpacing.lg),

            // Parameters
            Row(
              children: [
                Expanded(
                  child: _NumberField(
                    label: 'Presupuesto',
                    controller: _budget,
                    suffix: 'USD',
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: _Readout(
                    label: 'Rep. mínima',
                    value: '≥ ${(_minReputation * 100).round()}%',
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: _FanOutStepper(
                    value: _fanOut,
                    onChanged: (v) => setState(() => _fanOut = v),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Slider(
              value: _minReputation,
              min: 0,
              max: 1,
              divisions: 20,
              label: '${(_minReputation * 100).round()}%',
              onChanged: (v) => setState(() => _minReputation = v),
            ),
            const SizedBox(height: AppSpacing.sm),

            if (_mode == TaskInputMode.text) ...[
              ChatPanel(messages: chat),
              const SizedBox(height: AppSpacing.lg),
            ],

            FilledButton.icon(
              onPressed: _submitting ? null : _submit,
              icon: _submitting
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send, size: 18),
              label: const Text('Enviar Solicitud'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _label(BuildContext context, String text) => Text(
        text,
        style: Theme.of(context)
            .textTheme
            .labelMedium
            ?.copyWith(color: AppTokens.of(context).textMuted),
      );
}

class _CapabilityField extends StatelessWidget {
  const _CapabilityField({required this.capabilityId});
  final String capabilityId;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.md,
      ),
      decoration: BoxDecoration(
        color: tokens.input,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: tokens.borderActive),
      ),
      child: Row(
        children: [
          Icon(Icons.search, size: 16, color: tokens.textMuted),
          const SizedBox(width: AppSpacing.sm),
          Text(capabilityId, style: Theme.of(context).textTheme.bodyMedium),
          const Spacer(),
          AppBadge(label: 'T-beta', color: tokens.accentPink, mono: true),
        ],
      ),
    );
  }
}

class _ModeToggle extends StatelessWidget {
  const _ModeToggle({required this.mode, required this.onChanged});
  final TaskInputMode mode;
  final ValueChanged<TaskInputMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<TaskInputMode>(
      style: const ButtonStyle(visualDensity: VisualDensity.compact),
      segments: const [
        ButtonSegment(
          value: TaskInputMode.text,
          label: Text('Texto'),
          icon: Icon(Icons.text_fields, size: 14),
        ),
        ButtonSegment(
          value: TaskInputMode.audio,
          label: Text('Audio'),
          icon: Icon(Icons.mic, size: 14),
        ),
      ],
      selected: {mode},
      onSelectionChanged: (s) => onChanged(s.first),
    );
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField({
    required this.label,
    required this.controller,
    this.suffix,
  });
  final String label;
  final TextEditingController controller;
  final String? suffix;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.textMuted)),
        const SizedBox(height: AppSpacing.xs),
        TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(suffixText: suffix, isDense: true),
        ),
      ],
    );
  }
}

class _Readout extends StatelessWidget {
  const _Readout({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.textMuted)),
        const SizedBox(height: AppSpacing.xs),
        Container(
          height: 48,
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
          decoration: BoxDecoration(
            color: tokens.input,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: tokens.borderSubtle),
          ),
          child: Text(value, style: Theme.of(context).textTheme.bodyMedium),
        ),
      ],
    );
  }
}

class _FanOutStepper extends StatelessWidget {
  const _FanOutStepper({required this.value, required this.onChanged});
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Fan-out',
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.textMuted)),
        const SizedBox(height: AppSpacing.xs),
        Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
          decoration: BoxDecoration(
            color: tokens.input,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: tokens.borderSubtle),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              GestureDetector(
                onTap: value > 1 ? () => onChanged(value - 1) : null,
                child: Icon(Icons.remove, size: 16, color: tokens.textMuted),
              ),
              Text('$value', style: Theme.of(context).textTheme.bodyMedium),
              GestureDetector(
                onTap: value < 5 ? () => onChanged(value + 1) : null,
                child: Icon(Icons.add, size: 16, color: tokens.textMuted),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
