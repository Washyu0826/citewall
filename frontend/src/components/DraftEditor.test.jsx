import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '../lib/i18n.js';
import DraftEditor from './DraftEditor.jsx';

function renderEditor(draft) {
  render(
    <DraftEditor
      initialDraft={draft}
      citationLookup={{}}
      caseId="CASE-T"
      rejectionId="R1"
      token="tok"
      canExport
      role="attorney"
    />
  );
  return screen.getAllByTestId('draft-line');
}

function editLine(line, text) {
  fireEvent.keyDown(line, { key: 'e' });
  // Scope to the line: the editor also has an "add a line" textbox.
  const box = within(screen.getAllByTestId('draft-line')[0]).getByRole('textbox');
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true });
}

describe('DraftEditor commitEdit — CITATION_REMOVED gate', () => {
  it('splits a zh-TW draft into one line per sentence', () => {
    expect(renderEditor('第一句[CITATION_REMOVED]。第二句。')).toHaveLength(2);
  });

  it('A cannot accept a line that still carries [CITATION_REMOVED]', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    fireEvent.keyDown(first, { key: 'a' });
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });

  it('an edit that keeps the marker leaves the line pending', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    editLine(first, '改寫過但仍有[CITATION_REMOVED]。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });

  it('an edit that removes the marker accepts the line', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    editLine(first, '已由律師改寫。');
    const line = screen.getAllByTestId('draft-line')[0];
    expect(line).toHaveAttribute('data-status', 'accepted');
    expect(line).toHaveTextContent('已由律師改寫。');
  });
});

describe('DraftEditor — Q14/Q17 [UNSUPPORTED_REF_n] gate', () => {
  const DRAFT = '引證1揭示冷卻板[GROUNDED_REF_1]。惟其未教示無線充電線圈[UNSUPPORTED_REF_1]。';

  it('renders the unsupported ref as a warning pill', () => {
    renderEditor(DRAFT);
    expect(screen.getByTestId('unsupported-ref')).toHaveTextContent('1');
  });

  it('A cannot accept the unsupported sentence, but can accept the supported one', () => {
    const [first, second] = renderEditor(DRAFT);
    fireEvent.keyDown(second, { key: 'a' });
    fireEvent.keyDown(first, { key: 'a' });
    const lines = screen.getAllByTestId('draft-line');
    expect(lines[0]).toHaveAttribute('data-status', 'accepted');
    expect(lines[1]).toHaveAttribute('data-status', 'pending');
    expect(within(lines[1]).getByTestId('line-accept-blocked')).toBeInTheDocument();
  });

  it('an edit that keeps [UNSUPPORTED_REF_n] stays pending; removing it accepts', () => {
    renderEditor('惟其未教示無線充電線圈[UNSUPPORTED_REF_1]。');
    editLine(screen.getAllByTestId('draft-line')[0], '改寫後仍引用[UNSUPPORTED_REF_1]。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
    editLine(screen.getAllByTestId('draft-line')[0], '律師已依前案段落改寫。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'accepted');
  });
});
