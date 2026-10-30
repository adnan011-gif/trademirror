import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import App from '../App';

import {
  mockSamples,
  mockMixedResponse,
  mockCleanResponse,
  mockTruncatedEvidenceResponse,
} from './fixtures';
import { isAnalysisResponse } from '../types';

describe('TradeMirror Frontend Application Tests', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      if (url.startsWith('/api/sample/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({
            'content-type': 'application/json',
            'x-request-id': 'req-sample-1234',
          }),
          json: () => Promise.resolve(mockMixedResponse),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({ status: 'ok' }),
      } as Response);
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('1. landing renders and the sample button calls analyzeSample("mixed")', async () => {
    render(<App />);

    // Wait for samples to load and check hero text
    expect(
      await screen.findByText(/Find the two or three habits costing you the most money/i),
    ).toBeInTheDocument();

    // Check primary button is present
    const runBtn = screen.getByRole('button', { name: /Run Analysis/i });
    expect(runBtn).toBeInTheDocument();

    fireEvent.click(runBtn);

    // Verify analyzeSample called with 'mixed'
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/sample/mixed',
        expect.objectContaining({
          headers: expect.objectContaining({ Accept: 'application/json' }),
        }),
      );
    });
  });

  it('2. results screen from mixed fixture: headline shows right total, 3 cards in rank order, overlap line only where overlap_share > 0', async () => {
    render(<App />);

    const runBtn = await screen.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtn);

    // Headline check
    expect(
      await screen.findByText(/3 habits cost you about ₹1,48,573 this month/i),
    ).toBeInTheDocument();

    // Three habit cards in order
    const cardHolding = screen.getByTestId('habit-card-holding_losers');
    const cardRevenge = screen.getByTestId('habit-card-revenge_trading');
    const cardOvertrading = screen.getByTestId('habit-card-overtrading');

    expect(cardHolding).toBeInTheDocument();
    expect(cardRevenge).toBeInTheDocument();
    expect(cardOvertrading).toBeInTheDocument();

    // Overlap line only on revenge_trading (overlap_share > 0)
    expect(cardHolding).not.toHaveTextContent(/before removing overlap/i);
    expect(cardRevenge).toHaveTextContent(/before removing overlap with Holding losing trades too long/i);
    expect(cardOvertrading).not.toHaveTextContent(/before removing overlap/i);
  });

  it('3. not-material fixture shows the friendly state and no cards', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: () => Promise.resolve(mockCleanResponse),
      } as Response);
    });

    render(<App />);

    const runBtn = await screen.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtn);

    expect(
      await screen.findByText(/No behavioral habit cleared the evidence bar this month/i),
    ).toBeInTheDocument();

    expect(screen.queryByTestId('habit-card-holding_losers')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try another month/i })).toBeInTheDocument();
  });

  it('4. evidence modal opens, shows truncation note, closes on Escape and returns focus', async () => {
    render(<App />);

    const runBtn = await screen.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtn);

    await screen.findByText(/3 habits cost you about/i);

    // Click 'Show the trades' on the first habit card (holding_losers)
    const showTradesButtons = screen.getAllByRole('button', { name: /Show the trades/i });
    const triggerButton = showTradesButtons[0];
    triggerButton.focus();
    fireEvent.click(triggerButton);

    // Modal dialog is open
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();

    // Shows truncation note
    expect(
      screen.getByText(/Showing the 2 largest losses of 33 flagged trades/i),
    ).toBeInTheDocument();

    // Press Escape to close
    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    // Check focus returned
    expect(document.activeElement).toBe(triggerButton);
  });

  it('5. 413, 422, 429, 500 responses map to the right messages and show request id', async () => {
    const errorCases = [
      {
        status: 413,
        detail: 'File exceeds maximum upload size of 5 MB',
        expected: 'File exceeds maximum upload size of 5 MB',
        requestId: 'req-413',
      },
      {
        status: 422,
        detail: "Missing required columns: ['order_id']",
        expected: "Missing required columns: ['order_id']",
        requestId: 'req-422',
      },
      {
        status: 429,
        detail: 'Rate limit reached. Please wait 15 seconds.',
        expected: 'Rate limit reached. Please wait 15 seconds.',
        requestId: 'req-429',
      },
      {
        status: 500,
        detail: 'An internal server error occurred.',
        expected: 'A server error occurred while processing the request.',
        requestId: 'req-500',
      },
    ];

    for (const ec of errorCases) {
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        if (url === '/api/samples') {
          return Promise.resolve({
            ok: true,
            status: 200,
            headers: new Headers(),
            json: () => Promise.resolve(mockSamples),
          } as Response);
        }
        return Promise.resolve({
          ok: false,
          status: ec.status,
          headers: new Headers({
            'content-type': 'application/json',
            'x-request-id': ec.requestId,
          }),
          json: () => Promise.resolve({ detail: ec.detail, request_id: ec.requestId }),
        } as Response);
      });

      const { unmount } = render(<App />);
      const runBtn = await screen.findByRole('button', { name: /Run Analysis/i });
      fireEvent.click(runBtn);

      const errorPanel = await screen.findByTestId('error-panel');
      expect(errorPanel).toHaveTextContent(ec.expected);
      expect(errorPanel).toHaveTextContent(ec.requestId);

      unmount();
    }
  });

  it('6. cold-start message appears after 5 seconds with fake timers', async () => {
    vi.useFakeTimers();

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      // Never resolving promise to simulate slow/cold request
      return new Promise(() => {});
    });

    render(<App />);

    // Fast-forward samples fetch
    await act(async () => {
      await Promise.resolve();
    });

    const runBtn = screen.getByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtn);

    // Loading skeleton is visible immediately
    expect(screen.getByTestId('loading-box')).toBeInTheDocument();
    expect(screen.queryByText(/Waking up the server/i)).not.toBeInTheDocument();

    // Advance timer by 5000 ms
    act(() => {
      vi.advanceTimersByTime(5001);
    });

    expect(
      screen.getByText(/Waking up the server\. The first request after a quiet period can take up to a minute\./i),
    ).toBeInTheDocument();
  });

  it('7. upload with non-.csv file is rejected client-side without calling API', async () => {
    render(<App />);

    const invalidFile = new File(['hello'], 'orders.pdf', { type: 'application/pdf' });
    const dropzone = await screen.findByTestId('upload-dropzone');

    const input = dropzone.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeInTheDocument();

    fireEvent.change(input, { target: { files: [invalidFile] } });

    expect(await screen.findByText(/Please select a valid CSV file/i)).toBeInTheDocument();

    // Verify /api/analyze was NOT called
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/api/analyze',
      expect.anything(),
    );
  });

  it('8. isAnalysisResponse guard rejects malformed payload and error panel shows', async () => {
    const malformed = {
      material: true,
      // Missing dataset and context
      habits: [],
    };
    expect(isAnalysisResponse(malformed)).toBe(false);

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ 'x-request-id': 'req-malformed-999' }),
        json: () => Promise.resolve(malformed),
      } as Response);
    });

    render(<App />);

    const runBtn = await screen.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtn);

    const errorPanel = await screen.findByTestId('error-panel');
    expect(errorPanel).toHaveTextContent(/Received an invalid response format from the server/i);
    expect(errorPanel).toHaveTextContent('req-malformed-999');
  });

  it('9. renders three fixtures and asserts every displayed number equals the fixture value', async () => {
    // 1. Not-material fixture (mockCleanResponse)
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: () => Promise.resolve(mockCleanResponse),
      } as Response);
    });

    const cleanRender = render(<App />);
    const runBtnClean = await cleanRender.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtnClean);

    // Verify not-material title from summary and exact trade count (95)
    expect(await cleanRender.findByText(mockCleanResponse.summary)).toBeInTheDocument();
    expect(cleanRender.getByText(`${mockCleanResponse.dataset.n_trades} trades analysed.`)).toBeInTheDocument();
    cleanRender.unmount();

    // 2. Mixed-like fixture (mockMixedResponse)
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: () => Promise.resolve(mockMixedResponse),
      } as Response);
    });

    const mixedRender = render(<App />);
    const runBtnMixed = await mixedRender.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtnMixed);

    // Headline: cost 148,573, n_trades 121, win_rate 40.5%, gross_pnl -1,27,453
    expect(await mixedRender.findByText(/3 habits cost you about ₹1,48,573 this month/i)).toBeInTheDocument();
    expect(mixedRender.getByText(/121 trades, 40.5% winners, gross P&L -₹1,27,453\./i)).toBeInTheDocument();

    // Habit cards: costs ₹97,841, ₹28,103 (with ₹48,177 before overlap), ₹22,629
    expect(mixedRender.getByText('₹97,841')).toBeInTheDocument();
    expect(mixedRender.getByText('₹28,103')).toBeInTheDocument();
    expect(mixedRender.getByText(/₹48,177 before removing overlap with/i)).toBeInTheDocument();
    expect(mixedRender.getByText('₹22,629')).toBeInTheDocument();
    mixedRender.unmount();

    // 3. Truncated evidence fixture with n_trades = 77 and evidence 25 of 41 (mockTruncatedEvidenceResponse)
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/samples') {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers(),
          json: () => Promise.resolve(mockSamples),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: () => Promise.resolve(mockTruncatedEvidenceResponse),
      } as Response);
    });

    const truncRender = render(<App />);
    const runBtnTrunc = await truncRender.findByRole('button', { name: /Run Analysis/i });
    fireEvent.click(runBtnTrunc);

    // Headline with 77 trades, 42.8% win rate, -₹65,400 gross P&L, ₹52,100 cost
    expect(await truncRender.findByText(/1 habit cost you about ₹52,100 this month/i)).toBeInTheDocument();
    expect(truncRender.getByText(/77 trades, 42.8% winners, gross P&L -₹65,400\./i)).toBeInTheDocument();
    expect(truncRender.getByText('₹52,100')).toBeInTheDocument();

    // Open evidence modal and assert dynamic truncation numbers 25 of 41
    const showTradesBtn = truncRender.getByRole('button', { name: /Show the trades/i });
    fireEvent.click(showTradesBtn);

    const dialog = await truncRender.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(
      truncRender.getByText('Showing the 25 largest losses of 41 flagged trades'),
    ).toBeInTheDocument();

    // Assert exactly 25 rows rendered in the table
    const tableRows = dialog.querySelectorAll('tbody tr');
    expect(tableRows.length).toBe(25);
    truncRender.unmount();
  });
});
