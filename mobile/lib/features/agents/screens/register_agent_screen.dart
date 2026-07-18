import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/screen_header.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/domain/models/agent_registration.dart';

class RegisterAgentScreen extends ConsumerStatefulWidget {
  const RegisterAgentScreen({super.key});

  @override
  ConsumerState<RegisterAgentScreen> createState() =>
      _RegisterAgentScreenState();
}

class _RegisterAgentScreenState extends ConsumerState<RegisterAgentScreen> {
  final _name = TextEditingController();
  final _endpoint = TextEditingController();
  final _publicKey = TextEditingController();
  final _bearer = TextEditingController();
  final _listPrice = TextEditingController(text: '12.00');
  final _minPrice = TextEditingController(text: '8.00');
  final _capabilityInput = TextEditingController();

  final List<String> _capabilities = ['terraform.generate', 'infra.plan'];
  bool _bearerEnabled = false;
  bool _submitting = false;

  @override
  void dispose() {
    for (final c in [
      _name,
      _endpoint,
      _publicKey,
      _bearer,
      _listPrice,
      _minPrice,
      _capabilityInput,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  void _addCapability() {
    final value = _capabilityInput.text.trim();
    if (value.isEmpty || _capabilities.contains(value)) return;
    setState(() {
      _capabilities.add(value);
      _capabilityInput.clear();
    });
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty ||
        _endpoint.text.trim().isEmpty ||
        _capabilities.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Nombre, endpoint y al menos una capacidad.'),
        ),
      );
      return;
    }
    setState(() => _submitting = true);
    final registration = AgentRegistration(
      name: _name.text.trim(),
      endpointUrl: _endpoint.text.trim(),
      publicKey: _publicKey.text.trim(),
      capabilities: List.of(_capabilities),
      listPrice: double.tryParse(_listPrice.text.trim()) ?? 0,
      minPrice: double.tryParse(_minPrice.text.trim()) ?? 0,
      currency: 'USD',
      bearerToken: _bearerEnabled ? _bearer.text.trim() : null,
    );
    await ref
        .read(agentRegistrationRepositoryProvider)
        .register(registration);
    if (!mounted) return;
    setState(() => _submitting = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Agente "${registration.name}" registrado.')),
    );
    context.pop();
  }

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            40,
          ),
          children: [
            const ScreenHeader(title: 'Registrar Agente'),
            const SizedBox(height: AppSpacing.lg),

            _Field(
              label: 'Nombre del Agente',
              controller: _name,
              hint: 'ej. TerraformPro Agent',
            ),
            _Field(
              label: 'Endpoint URL',
              controller: _endpoint,
              hint: 'https://tu-agente.ejemplo.com',
              keyboardType: TextInputType.url,
            ),
            _Field(
              label: 'Clave Pública (ed25519)',
              controller: _publicKey,
              hint: 'ed25519:abc123def456…',
            ),

            _label(context, 'Capacidades'),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final c in _capabilities)
                  InputChip(
                    label: Text(c),
                    onDeleted: () => setState(() => _capabilities.remove(c)),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _capabilityInput,
                    decoration: const InputDecoration(
                      hintText: 'p. ej. code.review',
                      isDense: true,
                    ),
                    onSubmitted: (_) => _addCapability(),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                OutlinedButton(
                  onPressed: _addCapability,
                  child: const Text('Agregar'),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),

            // Bearer auth
            Row(
              children: [
                Expanded(child: _label(context, 'Autenticación Bearer')),
                Switch(
                  value: _bearerEnabled,
                  onChanged: (v) => setState(() => _bearerEnabled = v),
                ),
              ],
            ),
            if (_bearerEnabled) ...[
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _bearer,
                obscureText: true,
                decoration: const InputDecoration(
                  hintText: 'sk_live_a8f2c9d1e4b7…',
                  prefixIcon: Icon(Icons.key, size: 16),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),

            _label(context, 'Precios'),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Expanded(
                  child: _InlineNumber(
                    label: 'Precio público',
                    controller: _listPrice,
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: _InlineNumber(
                    label: 'Mínimo (privado)',
                    controller: _minPrice,
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: _InlineNumber(
                    label: 'Moneda',
                    controller: TextEditingController(text: 'USD'),
                    enabled: false,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                // ignore: deprecated_member_use
                color: tokens.accentGreen.withOpacity(0.10),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Row(
                children: [
                  Icon(Icons.lock_outline, size: 15, color: tokens.accentGreen),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      'Tu precio mínimo es privado y nunca se comparte.',
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: tokens.accentGreen),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.xl),

            FilledButton.icon(
              onPressed: _submitting ? null : _submit,
              icon: _submitting
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.rocket_launch_outlined, size: 18),
              label: const Text('Registrar Agente'),
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

class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.controller,
    this.hint,
    this.keyboardType,
  });

  final String label;
  final TextEditingController controller;
  final String? hint;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .labelMedium
                ?.copyWith(color: AppTokens.of(context).textMuted),
          ),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: controller,
            keyboardType: keyboardType,
            decoration: InputDecoration(hintText: hint),
          ),
        ],
      ),
    );
  }
}

class _InlineNumber extends StatelessWidget {
  const _InlineNumber({
    required this.label,
    required this.controller,
    this.enabled = true,
  });

  final String label;
  final TextEditingController controller;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: AppTokens.of(context).textMuted),
        ),
        const SizedBox(height: AppSpacing.xs),
        TextField(
          controller: controller,
          enabled: enabled,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(isDense: true),
        ),
      ],
    );
  }
}
