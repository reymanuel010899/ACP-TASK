/// The kind of event shown in the Home "Actividad reciente" feed.
enum ActivityKind {
  taskVerified,
  taskRejected,
  reputationUpdated,
  offerReceived,
}

/// A single row in the recent-activity feed on Home.
class RecentActivity {
  const RecentActivity({
    required this.id,
    required this.agentName,
    required this.kind,
    required this.detail,
    required this.timestamp,
  });

  final String id;
  final String agentName;
  final ActivityKind kind;
  final String detail;
  final DateTime timestamp;
}
