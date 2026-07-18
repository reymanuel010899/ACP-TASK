import 'package:agenttrust_mobile/domain/models/received_offer.dart';

/// The lifecycle stages of a task, matching the design's progress stepper:
/// Publicado → Buscando → Chat → Verifica → Ejecuta.
enum TaskStage {
  published('Publicado'),
  searching('Buscando'),
  chat('Chat'),
  verifying('Verifica'),
  executing('Ejecuta');

  const TaskStage(this.label);
  final String label;

  bool isAtOrBefore(TaskStage other) => index <= other.index;
}

/// Terminal trust outcome, mirroring the requester agent's classification
/// (`agents/requester/agent.py`): a task is only truly "done" when an
/// independent verification says so.
enum TaskOutcome {
  /// A2A COMPLETED and independently verified — the only trusted "done".
  verified,

  /// The verifier rejected the evidence. Not complete.
  rejected,

  /// Completed at A2A level but no independent verification available.
  unverified,

  /// Never reached a completed state.
  failed,
}

/// A requester task moving through the trust lifecycle. App-level aggregate
/// (not a wire schema): it composes offers, the selected offer, and the
/// current stage/outcome for the UI to render live.
class Task {
  const Task({
    required this.id,
    required this.capabilityId,
    required this.description,
    required this.budget,
    required this.currency,
    required this.minReputation,
    required this.fanOut,
    required this.stage,
    required this.createdAt,
    this.offers = const [],
    this.selectedOffer,
    this.outcome,
  });

  final String id;
  final String capabilityId;
  final String description;
  final double budget;
  final String currency;

  /// Minimum verification rate a candidate must clear (0..1), or null for any.
  final double? minReputation;

  /// How many providers to solicit offers from.
  final int fanOut;

  final TaskStage stage;
  final DateTime createdAt;
  final List<ReceivedOffer> offers;
  final ReceivedOffer? selectedOffer;
  final TaskOutcome? outcome;

  bool get isTerminal => outcome != null;

  /// Offers sorted ascending by price (cheapest first, as the design shows).
  List<ReceivedOffer> get offersByPrice {
    final sorted = [...offers]..sort((a, b) => a.price.compareTo(b.price));
    return sorted;
  }

  Task copyWith({
    TaskStage? stage,
    List<ReceivedOffer>? offers,
    ReceivedOffer? selectedOffer,
    TaskOutcome? outcome,
  }) {
    return Task(
      id: id,
      capabilityId: capabilityId,
      description: description,
      budget: budget,
      currency: currency,
      minReputation: minReputation,
      fanOut: fanOut,
      createdAt: createdAt,
      stage: stage ?? this.stage,
      offers: offers ?? this.offers,
      selectedOffer: selectedOffer ?? this.selectedOffer,
      outcome: outcome ?? this.outcome,
    );
  }
}
