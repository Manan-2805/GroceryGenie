import { TrendingUp, Users, DollarSign, ShoppingBag, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import React, { useState } from 'react';

import { SellerNav } from '../components/SellerNav';

export const SellerAnalysis: React.FC = () => {
  const [selectedMonth, setSelectedMonth] = useState('All');

  // Mock Sales Data
  const monthlyData = [
    { name: 'Jan', sales: 400, orders: 12 },
    { name: 'Feb', sales: 800, orders: 22 },
    { name: 'Mar', sales: 600, orders: 18 },
    { name: 'Apr', sales: 1200, orders: 35 },
    { name: 'May', sales: 1500, orders: 40 },
    { name: 'Jun', sales: 1300, orders: 38 },
  ];

  const categoryBreakdown = [
    { name: 'Produce', percentage: 40, color: '#A855F7', value: 520 }, // Purple
    { name: 'Dairy & Eggs', percentage: 25, color: '#3B82F6', value: 325 }, // Blue
    { name: 'Pantry', percentage: 15, color: '#10B981', value: 195 }, // Green
    { name: 'Beverages', percentage: 12, color: '#F59E0B', value: 156 }, // Amber
    { name: 'Bakery', percentage: 8, color: '#EF4444', value: 104 }, // Red
  ];

  // SVG Chart Calculations
  const maxSales = Math.max(...monthlyData.map(d => d.sales));
  const chartHeight = 200;
  const chartWidth = 500;
  
  // Create area path
  const points = monthlyData.map((d, index) => {
    const x = (index / (monthlyData.length - 1)) * chartWidth;
    const y = chartHeight - (d.sales / maxSales) * (chartHeight - 40) - 20;
    return { x, y, name: d.name, val: d.sales };
  });

  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];

  const pathD = (points.length > 0 && firstPoint) 
    ? `M ${firstPoint.x} ${firstPoint.y} ` + points.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ') 
    : '';

  const areaD = (points.length > 0 && lastPoint && firstPoint)
    ? `${pathD} L ${lastPoint.x} ${chartHeight} L ${firstPoint.x} ${chartHeight} Z`
    : '';

  return (
    <div className="w-full min-h-screen bg-gray-50/50 dark:bg-gray-950 text-left">
      <SellerNav />
      <div className="max-w-6xl mx-auto py-8 px-4 space-y-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
          <div>
            <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Sales Analysis</h1>
            <p className="text-sm text-gray-500">Real-time revenue metrics, shopping category breakdowns, and performance analytics</p>
          </div>
          <select
            value={selectedMonth}
            onChange={(e) => setSelectedMonth(e.target.value)}
            className="px-3 py-2 bg-white dark:bg-gray-900 border dark:border-gray-800 rounded-xl text-xs font-bold focus:outline-none"
          >
            <option value="All">All Time (H1 2026)</option>
            <option value="Q2">Q2 2026 Only</option>
            <option value="Q1">Q1 2026 Only</option>
          </select>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Gross Revenue</span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <DollarSign size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">€5,800.00</p>
              <span className="flex items-center gap-1 text-[10px] font-bold text-green-600 dark:text-green-400 mt-1">
                <ArrowUpRight size={14} />
                <span>+12.4% vs last month</span>
              </span>
            </div>
          </div>

          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Total Orders</span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <ShoppingBag size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">165 orders</p>
              <span className="flex items-center gap-1 text-[10px] font-bold text-green-600 dark:text-green-400 mt-1">
                <ArrowUpRight size={14} />
                <span>+8.2% vs last month</span>
              </span>
            </div>
          </div>

          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Avg Order Value</span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <TrendingUp size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">€35.15</p>
              <span className="flex items-center gap-1 text-[10px] font-bold text-red-500 dark:text-red-400 mt-1">
                <ArrowDownRight size={14} />
                <span>-2.1% vs last month</span>
              </span>
            </div>
          </div>

          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Active Customers</span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <Users size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">42 unique</p>
              <span className="flex items-center gap-1 text-[10px] font-bold text-green-600 dark:text-green-400 mt-1">
                <ArrowUpRight size={14} />
                <span>+15.3% vs last month</span>
              </span>
            </div>
          </div>
        </div>

        {/* Charts Section */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Revenue Trend Line Chart */}
          <div className="lg:col-span-2 p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm flex flex-col justify-between space-y-4">
            <div>
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">Revenue Growth Trend</h3>
              <p className="text-[11px] text-gray-400 mt-0.5">Sales performance over the last 6 months</p>
            </div>

            <div className="w-full overflow-x-auto">
              <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="w-full min-w-[400px] h-auto overflow-visible select-none">
                <defs>
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#A855F7" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="#A855F7" stopOpacity="0.00" />
                  </linearGradient>
                </defs>

                {/* Gridlines */}
                {[0, 0.25, 0.5, 0.75, 1].map((ratio, i) => {
                  const y = chartHeight - ratio * (chartHeight - 40) - 20;
                  const label = Math.round(ratio * maxSales);
                  return (
                    <g key={i} className="opacity-40">
                      <line x1="0" y1={y} x2={chartWidth} y2={y} stroke="currentColor" strokeWidth="0.5" strokeDasharray="3,3" className="text-gray-200 dark:text-gray-800" />
                      <text x="-10" y={y + 3} textAnchor="end" className="text-[9px] fill-gray-400 dark:fill-gray-600 font-semibold">€{label}</text>
                    </g>
                  );
                })}

                {/* Area under curve */}
                <path d={areaD} fill="url(#chartGradient)" />

                {/* Main line */}
                <path d={pathD} fill="none" stroke="#A855F7" strokeWidth="3" strokeLinecap="round" />

                {/* Data points */}
                {points.map((p, i) => (
                  <g key={i} className="group cursor-pointer">
                    <circle cx={p.x} cy={p.y} r="5" fill="#A855F7" className="stroke-white dark:stroke-gray-900 stroke-2 hover:r-7 transition-all" />
                    {/* Hover tooltip text */}
                    <text x={p.x} y={p.y - 12} textAnchor="middle" className="text-[10px] font-extrabold fill-purple-600 dark:fill-purple-400 opacity-0 group-hover:opacity-100 transition-opacity bg-black">
                      €{p.val}
                    </text>
                    {/* X axis labels */}
                    <text x={p.x} y={chartHeight - 2} textAnchor="middle" className="text-[9px] fill-gray-400 dark:fill-gray-600 font-bold uppercase tracking-wider">
                      {p.name}
                    </text>
                  </g>
                ))}
              </svg>
            </div>
          </div>

          {/* Category Share Donut Chart */}
          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm flex flex-col justify-between space-y-6">
            <div>
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">Category Sales Share</h3>
              <p className="text-[11px] text-gray-400 mt-0.5">Sales contribution breakdown by product category</p>
            </div>

            {/* Donut graphic */}
            <div className="flex justify-center items-center relative">
              <svg width="150" height="150" viewBox="0 0 100 100" className="transform -rotate-90">
                {/* Background track */}
                <circle cx="50" cy="50" r="40" fill="transparent" stroke="currentColor" strokeWidth="10" className="text-gray-100 dark:text-gray-800" />
                
                {/* Curated Segment circles stacked */}
                {(() => {
                  let accumulatedPercent = 0;
                  return categoryBreakdown.map((cat, i) => {
                    const radius = 40;
                    const circumference = 2 * Math.PI * radius;
                    const strokeDasharray = `${circumference}`;
                    const strokeDashoffset = circumference - (cat.percentage / 100) * circumference;
                    const rotation = (accumulatedPercent / 100) * 360;
                    accumulatedPercent += cat.percentage;
                    
                    return (
                      <circle
                        key={i}
                        cx="50"
                        cy="50"
                        r={radius}
                        fill="transparent"
                        stroke={cat.color}
                        strokeWidth="10"
                        strokeDasharray={strokeDasharray}
                        strokeDashoffset={strokeDashoffset}
                        transform={`rotate(${rotation} 50 50)`}
                        className="transition-all duration-500 hover:stroke-[12px] cursor-pointer"
                      />
                    );
                  });
                })()}
              </svg>
              {/* Inner details text */}
              <div className="absolute text-center">
                <p className="text-[9px] font-bold text-gray-400 uppercase">Sales</p>
                <p className="text-sm font-black text-gray-800 dark:text-gray-200">€1,300.00</p>
              </div>
            </div>

            {/* Legend list */}
            <div className="space-y-2 text-xs">
              {categoryBreakdown.map((cat) => (
                <div key={cat.name} className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: cat.color }} />
                    <span className="font-medium text-gray-600 dark:text-gray-400">{cat.name}</span>
                  </div>
                  <span className="font-extrabold text-gray-800 dark:text-gray-200">
                    {cat.percentage}% <span className="text-[10px] text-gray-400 font-normal">(€{cat.value})</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
