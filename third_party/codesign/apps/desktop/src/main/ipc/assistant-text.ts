export function stripAssistantArtifactText(text: string): string {
  return text
    .replace(/<artifact[\s\S]*?<\/artifact>/g, '')
    .replace(/<artifact\b[\s\S]*$/g, '')
    .replace(/```[a-zA-Z0-9]*\s*```/g, '')
    .trim();
}

export function finalAssistantTextForTurn(rawTurnText: string, streamedText: string): string {
  const fromTurn = stripAssistantArtifactText(rawTurnText);
  if (fromTurn.length > 0) return fromTurn;
  return stripAssistantArtifactText(streamedText);
}
