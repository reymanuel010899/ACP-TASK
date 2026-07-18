import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/progress_stepper.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';

// A light widget test. It deliberately avoids AppTheme.dark() / the full app,
// because those pull `google_fonts`, which tries to fetch over the network in
// a test sandbox. A minimal ThemeData carrying the AppTokens extension is all
// ProgressStepper needs.
void main() {
  testWidgets('ProgressStepper renders every lifecycle stage label',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(extensions: const [AppTokens.dark]),
        home: const Scaffold(
          body: ProgressStepper(current: TaskStage.chat),
        ),
      ),
    );

    for (final stage in TaskStage.values) {
      expect(find.text(stage.label), findsOneWidget);
    }
  });

  test('AppTokens.dark exposes the design accent colors', () {
    expect(AppTokens.dark.accentPurple.toARGB32(), 0xFFA855F7);
    expect(AppTokens.dark.accentGreen.toARGB32(), 0xFF10B981);
  });
}
