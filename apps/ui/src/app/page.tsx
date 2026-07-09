'use client';

import { useState, useEffect } from 'react';
import { uploadModel } from '@/lib/api';

interface HealthReport {
  health_score: number;
  sheets_found: string[];
  assumptions_count: number;
  issues: string[];
  status: string;
}

interface UploadResult {
  model_id: string;
  investment_id: string;
  health_report: HealthReport;
  parsed_sheets: string[];
  assumptions_count: number;
}

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Migrate legacy localStorage keys from projagent → investiq
  useEffect(() => {
    const migrations: [string, string][] = [
      ['projagent_model_id', 'investiq_model_id'],
      ['projagent_investment_id', 'investiq_investment_id'],
      ['projagent_persona', 'investiq_persona'],
    ];
    for (const [oldKey, newKey] of migrations) {
      const v = localStorage.getItem(oldKey);
      if (v && !localStorage.getItem(newKey)) {
        localStorage.setItem(newKey, v);
      }
      localStorage.removeItem(oldKey);
    }
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const data = await uploadModel(file);
      setResult(data);
      // Store IDs for other pages
      if (typeof window !== 'undefined') {
        localStorage.setItem('investiq_model_id', data.model_id);
        localStorage.setItem('investiq_investment_id', data.investment_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="text-center py-8">
        <h1 className="text-3xl font-bold text-white">InvestIQ</h1>
        <p className="text-d-muted mt-2">Upload your financial model to begin analysis</p>
      </div>

      {/* Upload Section */}
      <div className="max-w-xl mx-auto bg-d-card rounded-lg shadow p-6 border border-d-border">
        <h2 className="text-lg font-semibold mb-4 text-white">Upload Financial Model</h2>
        <div className="border-2 border-dashed border-d-border rounded-lg p-8 text-center">
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-d-muted file:mr-4 file:py-2 file:px-4
              file:rounded file:border-0 file:text-sm file:font-semibold
              file:bg-gold-500 file:text-white hover:file:bg-gold-600
              file:cursor-pointer file:shadow-sm"
          />
          {file && (
            <p className="mt-2 text-sm text-slate-300">
              Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </p>
          )}
        </div>
        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className="mt-4 w-full bg-gold-500 text-white font-semibold py-2.5 px-4 rounded hover:bg-gold-600
            disabled:bg-gray-500 disabled:text-gray-300 disabled:cursor-not-allowed transition shadow-sm"
        >
          {uploading ? 'Processing...' : 'Upload & Analyze'}
        </button>
        {error && <p className="mt-2 text-red-400 text-sm">{error}</p>}
      </div>

      {/* Results */}
      {result && (
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Health Report */}
          <div className="bg-d-card rounded-lg shadow p-6 border border-d-border">
            <h3 className="text-lg font-semibold mb-3 text-white">Model Health Report</h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-3 bg-d-bg rounded border border-d-border">
                <div className={`text-3xl font-bold ${
                  result.health_report.health_score >= 80 ? 'text-green-400' :
                  result.health_report.health_score >= 50 ? 'text-gold-500' : 'text-red-400'
                }`}>
                  {result.health_report.health_score}
                </div>
                <div className="text-sm text-d-muted">Health Score</div>
              </div>
              <div className="text-center p-3 bg-d-bg rounded border border-d-border">
                <div className="text-3xl font-bold text-white">
                  {result.parsed_sheets.length}
                </div>
                <div className="text-sm text-d-muted">Sheets Parsed</div>
              </div>
              <div className="text-center p-3 bg-d-bg rounded border border-d-border">
                <div className="text-3xl font-bold text-white">
                  {result.assumptions_count}
                </div>
                <div className="text-sm text-d-muted">Assumptions</div>
              </div>
            </div>

            <div className={`inline-block px-3 py-1 rounded text-sm font-semibold ${
              result.health_report.status === 'HEALTHY' ? 'bg-green-900/30 text-green-400' :
              result.health_report.status === 'DEGRADED' ? 'bg-yellow-900/30 text-yellow-400' :
              'bg-red-900/30 text-red-400'
            }`}>
              {result.health_report.status}
            </div>

            {result.health_report.issues.length > 0 && (
              <div className="mt-3">
                <h4 className="text-sm font-medium text-white">Issues:</h4>
                <ul className="list-disc list-inside text-sm text-red-400">
                  {result.health_report.issues.map((issue, i) => (
                    <li key={i}>{issue}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Sheets */}
          <div className="bg-d-card rounded-lg shadow p-6 border border-d-border">
            <h3 className="text-lg font-semibold mb-3 text-white">Parsed Sheets</h3>
            <div className="flex flex-wrap gap-2">
              {result.parsed_sheets.map((sheet) => (
                <span key={sheet} className="px-3 py-1 bg-d-hover text-white rounded text-sm border border-navy-100">
                  {sheet}
                </span>
              ))}
            </div>
          </div>

          {/* IDs for reference */}
          <div className="bg-d-card rounded-lg shadow p-6 border border-d-border">
            <h3 className="text-lg font-semibold mb-3 text-white">Reference IDs</h3>
            <div className="space-y-1 text-sm font-mono">
              <p><span className="text-d-muted">Model ID:</span> {result.model_id}</p>
              <p><span className="text-d-muted">Investment ID:</span> {result.investment_id}</p>
            </div>
            <p className="mt-3 text-sm text-d-muted">
              Navigate to Dashboard, Sensitivity, Monte Carlo, or other pages to analyze this model.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
