import 'package:agenttrust_mobile/domain/models/agent_summary.dart';
import 'package:agenttrust_mobile/domain/models/chat_message.dart';
import 'package:agenttrust_mobile/domain/models/principal.dart';
import 'package:agenttrust_mobile/domain/models/recent_activity.dart';
import 'package:agenttrust_mobile/domain/models/reputation_record.dart';
import 'package:agenttrust_mobile/domain/models/user_profile.dart';

/// Static demo data powering the mock repositories. Values mirror the Pencil
/// design so the app matches the mockups screen-for-screen.
abstract final class DemoFixtures {
  static const capabilityTerraform = 'terraform.generate';

  static ReputationRecord _rep(
    String principalId,
    int verified,
    int rejected,
    String capabilityId,
  ) {
    final total = verified + rejected;
    return ReputationRecord(
      principalId: principalId,
      capabilityId: capabilityId,
      tasksVerified: verified,
      tasksRejected: rejected,
      verificationRate: total == 0 ? null : verified / total,
      updatedAt: DateTime(2026, 7, 17, 9, 41),
    );
  }

  static AgentSummary _agent(
    String id,
    String name,
    double price,
    int verified,
    int rejected, {
    String capabilityId = capabilityTerraform,
    String? endpoint,
  }) {
    return AgentSummary(
      principalId: id,
      displayName: name,
      capabilityId: capabilityId,
      listPrice: price,
      currency: 'USD',
      endpointUrl: endpoint,
      reputation: _rep(id, verified, rejected, capabilityId),
    );
  }

  /// The signed-in operator.
  static const Principal me = Principal(
    principalId: 'prin_rey_ferreras',
    publicKey: 'k9Xm2pQ7rT4vW1yA3bC5dE6fG8hJ0kL2mN4oP6qR8sT=',
    displayName: 'Rey Ferreras',
  );

  static final UserProfile profile = UserProfile(
    principal: me,
    verifiedCount: 2847,
    activeCount: 156,
    verificationRate: 0.992,
    capabilities: const ['terraform.generate', 'infra.plan'],
  );

  /// Registry / featured agents.
  static final List<AgentSummary> agents = [
    _agent('prin_terraformpro', 'TerraformPro', 8, 138, 4,
        endpoint: 'https://terraformpro.example'),
    _agent('prin_datapipeline', 'DataPipeline', 11, 96, 6,
        capabilityId: 'data.pipeline'),
    _agent('prin_codereviewer', 'CodeReviewer', 5, 210, 9,
        capabilityId: 'code.review'),
    _agent('prin_infrabot', 'InfraBot v2', 11.5, 61, 8),
    _agent('prin_cloudforge', 'CloudForge', 14, 45, 2),
    _agent('prin_budgetinfra', 'BudgetInfra', 4, 0, 0),
    _agent('prin_fastinfra', 'FastInfra', 9, 12, 1),
  ];

  static List<AgentSummary> featured() =>
      agents.where((a) => a.capabilityId == capabilityTerraform).toList();

  /// Home "Actividad reciente".
  static List<RecentActivity> recentActivity() => [
        RecentActivity(
          id: 'act_1',
          agentName: 'TerraformPro',
          kind: ActivityKind.taskVerified,
          detail: 'Tarea verificada',
          timestamp: DateTime(2026, 7, 17, 9, 39),
        ),
        RecentActivity(
          id: 'act_2',
          agentName: 'DataPipeline',
          kind: ActivityKind.taskVerified,
          detail: 'Tarea verificada',
          timestamp: DateTime(2026, 7, 17, 9, 12),
        ),
        RecentActivity(
          id: 'act_3',
          agentName: 'CodeReviewer',
          kind: ActivityKind.reputationUpdated,
          detail: 'Reputación actualizada',
          timestamp: DateTime(2026, 7, 17, 8, 58),
        ),
      ];

  /// Scripted "Chat con el agente" for the terraform capability.
  static List<ChatMessage> scriptedChat() => [
        ChatMessage(
          id: 'm1',
          role: ChatRole.agent,
          text:
              'Hola. Necesito algunos detalles para generar tu template '
              'Terraform. ¿Qué tipo de contenedores quieres desplegar?',
          timestamp: DateTime(2026, 7, 17, 9, 40),
        ),
        ChatMessage(
          id: 'm2',
          role: ChatRole.user,
          text: 'Docker containers con una app Node.js y un servicio Redis.',
          timestamp: DateTime(2026, 7, 17, 9, 40, 30),
        ),
        ChatMessage(
          id: 'm3',
          role: ChatRole.agent,
          text:
              'Perfecto. ¿Necesitas health checks personalizados o los '
              'estándar sobre el endpoint HTTP?',
          timestamp: DateTime(2026, 7, 17, 9, 41),
        ),
      ];

  /// The three competing offers shown in "Ofertas recibidas", in the order
  /// they arrive (the UI re-sorts ascending by price).
  static const List<({String principalId, String name, double price})>
      demoOffers = [
    (principalId: 'prin_infrabot', name: 'InfraBot v2', price: 11.5),
    (principalId: 'prin_cloudforge', name: 'CloudForge', price: 14),
    (principalId: 'prin_terraformpro', name: 'TerraformPro', price: 6),
  ];
}
