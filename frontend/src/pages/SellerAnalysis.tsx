import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { SellerReviews } from '../components/SellerReviews';
import { api, authService } from '../services/api';

type Period = 'day' | 'week' | 'month' | 'year';
type Report = {
  orders: number;
  units: number;
  revenue: string;
  profit: string;
  forecast_next_week: string | null;
  forecast_method: string;
  repeat_customers: number;
  unique_customers: number;
  low_stock: number;
  buckets: { period: string; orders: number; units: number; revenue: string; profit: string }[];
  best_selling: { name: string; units: number }[];
};

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' });
export const formatINR = (amount: string | number) => inr.format(Number(amount));

export const getSellerReport = async (period: Period, signal?: AbortSignal): Promise<Report> =>
  (await api.get<Report>('/seller/reports', { params: { period }, ...(signal ? { signal } : {}) }))
    .data;

export function SellerAnalysis() {
  const [period, setPeriod] = useState<Period>('month');
  const owner = useQuery({ queryKey: ['report-owner'], queryFn: () => authService.getMe() });
  const query = useQuery<Report>({
    queryKey: ['seller-report', owner.data?.id, period],
    enabled: owner.data?.role === 'seller',
    queryFn: ({ signal }) => getSellerReport(period, signal),
  });
  const report = query.data;
  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-3xl font-semibold">Sales reports</h1>
        <div className="flex flex-wrap items-end gap-4">
          <label className="grid gap-1">
            Group sales by
            <select
              className="glass-card p-2"
              value={period}
              onChange={(event) => setPeriod(event.target.value as Period)}
            >
              <option value="day">Day</option>
              <option value="week">Week</option>
              <option value="month">Month</option>
              <option value="year">Year</option>
            </select>
          </label>
          <a
            className="rounded-lg bg-accent px-4 py-2 text-white"
            href={`/api/v1/seller/reports/csv?period=${period}`}
          >
            Download CSV
          </a>
        </div>
      </div>
      {owner.isError || query.isError ? (
        <div role="alert">
          The sales report couldn’t be loaded.{' '}
          <button
            type="button"
            onClick={() => {
              void owner.refetch();
              void query.refetch();
            }}
          >
            Retry
          </button>
        </div>
      ) : report === undefined ? (
        <p role="status">Loading your sales report…</p>
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-3">
            {[
              ['Delivered revenue', formatINR(report.revenue)],
              ['Gross profit', formatINR(report.profit)],
              ['Delivered orders', report.orders],
              ['Units sold', report.units],
              ['Repeat customers', `${report.repeat_customers} of ${report.unique_customers}`],
              ['Low-stock products', report.low_stock],
            ].map(([name, value]) => (
              <div className="glass-card p-4" key={name}>
                <dt>{name}</dt>
                <dd className="text-2xl font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
          <section className="glass-card space-y-2 p-4">
            <h2 className="text-lg font-semibold">Next week’s simulated sales estimate</h2>
            <p>
              {report.forecast_next_week === null
                ? 'Eight complete weeks of sales data are required.'
                : formatINR(report.forecast_next_week)}
            </p>
            <p className="text-sm">{report.forecast_method}</p>
          </section>
          <section className="glass-card space-y-2 p-4">
            <h2 className="text-lg font-semibold">Best-selling products</h2>
            {report.best_selling.length === 0 ? (
              <p>No delivered sales yet.</p>
            ) : (
              <ol className="list-inside list-decimal">
                {report.best_selling.map((product) => (
                  <li key={product.name}>
                    {product.name} · {product.units} units
                  </li>
                ))}
              </ol>
            )}
          </section>
          {report.buckets.length > 0 && (
            <div className="glass-card overflow-x-auto p-4">
              <table className="w-full text-left">
                <caption className="pb-2 text-lg font-semibold">Delivered sales history</caption>
                <thead>
                  <tr>
                    <th scope="col">Period</th>
                    <th scope="col">Orders</th>
                    <th scope="col">Units</th>
                    <th scope="col">Revenue</th>
                    <th scope="col">Gross profit</th>
                  </tr>
                </thead>
                <tbody>
                  {report.buckets.map((row) => (
                    <tr className="border-t" key={row.period}>
                      <th scope="row" className="py-2 font-normal">
                        {row.period}
                      </th>
                      <td>{row.orders}</td>
                      <td>{row.units}</td>
                      <td>{formatINR(row.revenue)}</td>
                      <td>{formatINR(row.profit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {owner.data?.role === 'seller' && <SellerReviews account={owner.data.id} />}
    </main>
  );
}
