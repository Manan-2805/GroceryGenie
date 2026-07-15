import { ChevronUp, ChevronDown, Download } from 'lucide-react';
import React, { useState, useMemo } from 'react';

export type Column<T> = {
  key: string;
  header: string;
  sortable?: boolean;
  filterable?: boolean;
  filterType?: 'text' | 'select';
  filterOptions?: string[];
  render?: (value: any, item: T) => React.ReactNode;
  maxWidth?: string;
}

type DataTableProps<T> = {
  columns: Column<T>[];
  data: T[];
  noDataMessage?: string;
  maxHeight?: string;
  exportFileName?: string;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  noDataMessage = 'No data available',
  maxHeight = 'max-h-[500px]',
  exportFileName = 'export',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [filters, setFilters] = useState<Record<string, string>>({});

  // Get distinct select options for columns that are select filterable and don't specify options
  const autoFilterOptions = useMemo(() => {
    const optionsMap: Record<string, string[]> = {};
    columns.forEach((col) => {
      if (col.filterable && col.filterType === 'select' && !col.filterOptions) {
        const values = data.map((item) => String(item[col.key] ?? '')).filter(Boolean);
        optionsMap[col.key] = Array.from(new Set(values));
      }
    });
    return optionsMap;
  }, [columns, data]);

  // Handle sort toggle
  const handleSort = (key: string) => {
    if (sortKey === key) {
      if (sortDir === 'asc') {
        setSortDir('desc');
      } else {
        setSortKey(null);
      }
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  // Handle filter change
  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => {
      const next = { ...prev };
      if (!value) {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  };

  // Filtered and sorted data
  const processedData = useMemo(() => {
    let result = [...data];

    // Apply filters
    Object.entries(filters).forEach(([key, filterValue]) => {
      const col = columns.find((c) => c.key === key);
      const isSelect = col?.filterType === 'select';

      result = result.filter((item) => {
        const val = String(item[key] ?? '').toLowerCase();
        const fVal = filterValue.toLowerCase();
        if (isSelect) {
          return val === fVal;
        }
        return val.includes(fVal);
      });
    });

    // Apply sort
    if (sortKey) {
      result.sort((a, b) => {
        let valA = a[sortKey];
        let valB = b[sortKey];

        // Handle numeric conversion if possible
        const numA = Number(valA);
        const numB = Number(valB);
        if (!isNaN(numA) && !isNaN(numB)) {
          valA = numA;
          valB = numB;
        } else {
          valA = String(valA ?? '').toLowerCase();
          valB = String(valB ?? '').toLowerCase();
        }

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [data, filters, sortKey, sortDir, columns]);

  // Export to CSV
  const handleExportCSV = () => {
    if (processedData.length === 0) return;

    // Header row
    const headers = columns.map((col) => `"${col.header.replace(/"/g, '""')}"`).join(',');

    // Data rows
    const rows = processedData.map((item) => {
      return columns
        .map((col) => {
          let val = item[col.key];
          // If complex object or array, stringify
          if (typeof val === 'object' && val !== null) {
            val = JSON.stringify(val);
          }
          const cleanVal = String(val ?? '').replace(/"/g, '""');
          return `"${cleanVal}"`;
        })
        .join(',');
    });

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers, ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `${exportFileName}_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="w-full flex flex-col bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden shadow-sm">
      {/* Top action bar */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800 flex justify-between items-center gap-4 bg-gray-50 dark:bg-gray-900/50">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">
          Showing {processedData.length} of {data.length} entries
        </span>
        <button
          onClick={handleExportCSV}
          disabled={processedData.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 disabled:hover:bg-purple-600 text-white rounded-lg text-xs font-bold transition shadow-sm"
        >
          <Download size={14} />
          <span>Export CSV</span>
        </button>
      </div>

      {/* Responsive Table container with fixed size and internal scroll */}
      <div className={`w-full overflow-x-auto overflow-y-auto ${maxHeight}`}>
        <table className="w-full text-left border-collapse min-w-[600px]">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 text-xs font-bold text-gray-600 dark:text-gray-400 uppercase tracking-wider sticky top-0 z-10">
              {columns.map((col) => (
                <th key={col.key} className="p-4 select-none">
                  <div className="flex flex-col gap-2">
                    <div
                      className={`flex items-center gap-1.5 ${
                        col.sortable ? 'cursor-pointer hover:text-gray-950 dark:hover:text-white' : ''
                      }`}
                      onClick={() => col.sortable && handleSort(col.key)}
                    >
                      <span>{col.header}</span>
                      {col.sortable && (
                        <span className="text-gray-400">
                          {sortKey === col.key ? (
                            sortDir === 'asc' ? (
                              <ChevronUp size={14} className="text-purple-600" />
                            ) : (
                              <ChevronDown size={14} className="text-purple-600" />
                            )
                          ) : (
                            <ChevronDown size={14} className="opacity-40" />
                          )}
                        </span>
                      )}
                    </div>

                    {/* Inline filters */}
                    {col.filterable && (
                      <div onClick={(e) => e.stopPropagation()}>
                        {col.filterType === 'select' ? (
                          <select
                            value={filters[col.key] || ''}
                            onChange={(e) => handleFilterChange(col.key, e.target.value)}
                            className="w-full px-2 py-1 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded text-[11px] font-medium text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-600"
                          >
                            <option value="">All</option>
                            {(col.filterOptions || autoFilterOptions[col.key] || []).map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type="text"
                            placeholder="Filter..."
                            value={filters[col.key] || ''}
                            onChange={(e) => handleFilterChange(col.key, e.target.value)}
                            className="w-full px-2 py-1 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded text-[11px] font-medium text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-600"
                          />
                        )}
                      </div>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            {processedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="p-8 text-center text-gray-500 dark:text-gray-400">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <span className="font-semibold">{noDataMessage}</span>
                    <span className="text-xs opacity-75">Try clearing filters or check back later</span>
                  </div>
                </td>
              </tr>
            ) : (
              processedData.map((item, rowIdx) => (
                <tr
                  key={item.id || rowIdx}
                  className="hover:bg-gray-50/50 dark:hover:bg-gray-900/20 text-gray-700 dark:text-gray-300 transition"
                >
                  {columns.map((col) => {
                    const value = item[col.key];
                    return (
                      <td key={col.key} className="p-4 align-middle">
                        <div
                          className={`truncate ${col.maxWidth || 'max-w-[200px]'}`}
                          title={typeof value === 'object' ? '' : String(value ?? '')}
                        >
                          {col.render ? col.render(value, item) : String(value ?? '')}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
