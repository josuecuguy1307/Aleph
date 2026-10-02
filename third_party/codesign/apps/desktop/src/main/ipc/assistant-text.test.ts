import { describe, expect, it } from 'vitest';
import { finalAssistantTextForTurn, stripAssistantArtifactText } from './assistant-text';

describe('assistant chat text helpers', () => {
  it('strips artifact blocks from chat prose', () => {
    expect(
      stripAssistantArtifactText(
        'Here is the update.\n<artifact identifier="x">huge jsx</artifact>\nDone.',
      ),
    ).toBe('Here is the update.\n\nDone.');
  });

  it('uses streamed text when turn_end message content is empty', () => {
    expect(finalAssistantTextForTurn('', 'I am placing the navigation now.')).toBe(
      'I am placing the navigation now.',
    );
  });

  it('does not preserve streamed artifact dumps as assistant chat', () => {
    expect(
      finalAssistantTextForTurn('', '<artifact identifier="x">function App() {}</artifact>'),
    ).toBe('');
  });

  it('prefers cleaned turn_end content over streamed fallback', () => {
    expect(finalAssistantTextForTurn('Final summary', 'I am working')).toBe('Final summary');
  });
});
