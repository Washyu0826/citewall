// Q15/Q16 claim-element comparison table + Q14/Q17 sentence-alignment gate.
import { test, expect } from '@playwright/test';
import { defaultAnalysisResponse, loginAsAlice, mockAnalyze } from './helpers/mock_backend.js';

function withTableAndUnsupported() {
  const r = defaultAnalysisResponse();
  r.drafts = [
    {
      ...r.drafts[0],
      draft_text:
        'The cited reference [GROUNDED_REF_1] discloses microchannels in a heat exchanger. ' +
        'Moreover, [UNSUPPORTED_REF_2] teaches a pump speed controller keyed to temperature.',
      grounded_citations: ['[GROUNDED_REF_1]', '[GROUNDED_REF_2]'],
      unsupported_citations: ['[GROUNDED_REF_2]'],
      alignment: [
        {
          sentence_index: 0,
          ref: '[GROUNDED_REF_1]',
          status: 'supported',
          lexical_support: 0.6,
          semantic_similarity: null,
          reason: 'lexical',
          missing_terms: [],
        },
        {
          sentence_index: 1,
          ref: '[GROUNDED_REF_2]',
          status: 'unsupported',
          lexical_support: 0.0,
          semantic_similarity: null,
          reason: 'low_overlap',
          missing_terms: ['pump', 'speed', 'controller'],
        },
      ],
    },
  ];
  r.element_tables = [
    {
      rejection_id: 'REJ-1',
      claim_no: 1,
      method: 'rules',
      model_used: null,
      evidence_available: true,
      elements: [
        {
          index: 1,
          text: 'A heat exchanger',
          is_preamble: true,
          status: 'disclosed',
          evidence: {
            ref_index: 1,
            patent_no: 'US7654321',
            section: 'claim_1',
            passage: 'A heat exchanger having a plurality of microchannels…',
          },
          lexical_support: 1.0,
          semantic_similarity: null,
          missing_terms: [],
        },
        {
          index: 2,
          text: 'microchannels having a non-uniform cross-section',
          is_preamble: false,
          status: 'partial',
          evidence: {
            ref_index: 1,
            patent_no: 'US7654321',
            section: 'claim_1',
            passage: 'microchannels with uniform rectangular cross-section',
          },
          lexical_support: 0.5,
          semantic_similarity: null,
          missing_terms: ['non-uniform'],
        },
        {
          index: 3,
          text: 'wherein the microchannels are copper',
          is_preamble: false,
          status: 'not_disclosed',
          evidence: {
            ref_index: 2,
            patent_no: 'US6543210',
            section: 'spec_para_12',
            passage: 'Copper provides superior thermal conductivity…',
          },
          lexical_support: 0.2,
          semantic_similarity: null,
          missing_terms: ['microchannels'],
        },
      ],
    },
  ];
  return r;
}

test.describe('Claim-element table & citation alignment', () => {
  test('table renders per element with findings and differences', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    mockAnalyze(page, withTableAndUnsupported());
    await page.getByRole('button', { name: /^分析 OA/ }).click();

    const table = page.getByTestId('element-table');
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table).toContainText('請求項要件對照表');
    const rows = table.getByTestId('element-row');
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveAttribute('data-status', 'disclosed');
    await expect(rows.nth(0)).toContainText('已揭露');
    await expect(rows.nth(1)).toContainText('部分揭露');
    await expect(rows.nth(1)).toContainText('前案段落未見：non-uniform');
    await expect(rows.nth(2)).toContainText('未揭露');

    // passage link → references pane (same contract as a citation pill)
    await rows.nth(2).getByTestId('element-evidence-link').click();
    await expect(page.getByText('US6543210').first()).toBeVisible();
  });

  test('a sentence with an unsupported citation cannot be accepted as-is', async ({
    page,
    viewport,
  }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    mockAnalyze(page, withTableAndUnsupported());
    await page.getByRole('button', { name: /^分析 OA/ }).click();

    await expect(page.getByTestId('alignment-banner')).toContainText('1');
    await expect(page.getByTestId('unsupported-ref')).toBeVisible();
    const lines = page.getByTestId('draft-line');
    await expect(lines).toHaveCount(2);
    await expect(lines.nth(1).getByTestId('line-accept-blocked')).toBeVisible();
    await expect(lines.nth(0).getByTestId('line-accept')).toBeVisible();
  });

  test('older gateways without element_tables render no table', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop layout');
    await loginAsAlice(page);
    mockAnalyze(page);
    await page.getByRole('button', { name: /^分析 OA/ }).click();
    await expect(page.getByTestId('verification-banner')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('element-table')).toHaveCount(0);
  });
});
