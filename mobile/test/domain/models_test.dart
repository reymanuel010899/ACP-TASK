import 'package:flutter_test/flutter_test.dart';

import 'package:agenttrust_mobile/domain/models/offer.dart';
import 'package:agenttrust_mobile/domain/models/received_offer.dart';
import 'package:agenttrust_mobile/domain/models/reputation_record.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';

void main() {
  group('ReputationRecord', () {
    test('neutral principal deserializes with null verification_rate', () {
      final record = ReputationRecord.fromJson({
        'principal_id': 'prin_new',
        'capability_id': 'terraform.generate',
        'tasks_verified': 0,
        'tasks_rejected': 0,
        'verification_rate': null,
        'updated_at': '2026-07-17T09:41:00Z',
      });

      expect(record.isNeutral, isTrue);
      expect(record.verificationRate, isNull);
    });

    test('non-neutral principal keeps its rate and round-trips', () {
      const json = {
        'principal_id': 'prin_terraformpro',
        'capability_id': 'terraform.generate',
        'tasks_verified': 138,
        'tasks_rejected': 4,
        'verification_rate': 0.9718,
        'updated_at': '2026-07-17T09:41:00.000Z',
      };
      final record = ReputationRecord.fromJson(json);

      expect(record.verificationRate, closeTo(0.9718, 1e-9));
      expect(record.toJson()['tasks_verified'], 138);
    });
  });

  group('Offer', () {
    test('serialized offer carries only the public price, never a reservation',
        () {
      const offer = Offer(
        taskId: 'task_1',
        capabilityId: 'terraform.generate',
        price: 6,
        currency: 'USD',
      );
      final json = offer.toJson();

      expect(json['type'], 'task.offer');
      expect(json['price'], 6);
      // The schema forbids any reservation/minimum field crossing the wire.
      expect(json.containsKey('reservation'), isFalse);
      expect(json.containsKey('min_price'), isFalse);
    });

    test('round-trips through fromJson/toJson', () {
      const offer = Offer(
        taskId: 'task_1',
        capabilityId: 'terraform.generate',
        price: 11.5,
        currency: 'USD',
      );
      final restored = Offer.fromJson(offer.toJson());
      expect(restored.price, 11.5);
      expect(restored.taskId, 'task_1');
    });
  });

  group('Task', () {
    ReceivedOffer offer(String name, double price) => ReceivedOffer(
          providerPrincipalId: 'prin_$name',
          providerName: name,
          offer: Offer(
            taskId: 'task_1',
            capabilityId: 'terraform.generate',
            price: price,
            currency: 'USD',
          ),
        );

    test('offersByPrice sorts ascending (cheapest first)', () {
      final task = Task(
        id: 'task_1',
        capabilityId: 'terraform.generate',
        description: 'demo',
        budget: 15,
        currency: 'USD',
        minReputation: 0.7,
        fanOut: 3,
        stage: TaskStage.chat,
        createdAt: DateTime(2026, 7, 17),
        offers: [offer('CloudForge', 14), offer('TerraformPro', 6), offer('InfraBot', 11.5)],
      );

      expect(
        task.offersByPrice.map((o) => o.price).toList(),
        [6, 11.5, 14],
      );
    });

    test('TaskStage order matches the design stepper', () {
      expect(
        TaskStage.values.map((s) => s.label).toList(),
        ['Publicado', 'Buscando', 'Chat', 'Verifica', 'Ejecuta'],
      );
    });
  });
}
