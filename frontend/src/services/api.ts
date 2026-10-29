import type { AnalysisResponse, HealthStatus } from '../types';

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/health');
  if (!response.ok) {
    throw new Error(`Failed to check health: ${response.statusText}`);
  }
  return response.json();
}

export async function analyzeOrdersCsv(file: File): Promise<AnalysisResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/api/analyze', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Failed to analyze orders: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchSampleDataset(name: string): Promise<string> {
  const response = await fetch(`/api/sample/${name}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch sample ${name}: ${response.statusText}`);
  }
  return response.text();
}
