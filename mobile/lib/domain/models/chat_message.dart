enum ChatRole { agent, user }

/// One turn in the "Chat con el agente" clarification dialogue.
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    required this.timestamp,
  });

  final String id;
  final ChatRole role;
  final String text;
  final DateTime timestamp;
}
