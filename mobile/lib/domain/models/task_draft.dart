/// How the requester described the task.
enum TaskInputMode { text, audio }

/// User input captured on the "Nueva Solicitud" screen, before a task exists.
class TaskDraft {
  const TaskDraft({
    required this.capabilityId,
    required this.description,
    required this.budget,
    required this.currency,
    required this.minReputation,
    required this.fanOut,
    required this.inputMode,
  });

  final String capabilityId;
  final String description;
  final double budget;
  final String currency;

  /// Minimum verification rate (0..1), or null for "any".
  final double? minReputation;
  final int fanOut;
  final TaskInputMode inputMode;
}
