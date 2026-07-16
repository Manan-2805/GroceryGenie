import { ChevronUp, ChevronDown, Download } from 'lucide-react';
import React, { useMemo, useState } from 'react';

export type Column<T> = {
  key: string;
  header: string;
  sortable?: boolean;
  filterable?: boolean;
  filterType?: 'text' | 'select';
  filterOptions?: string[];
  render?: (value: unknown, item: T) => React.ReactNode;
  maxWidth?: string;
};

type DataTableProps<T> = {
  columns: Column<T>[];
  data: T[];
  noDataMessage?: string;
  maxHeight?: string;
  exportFileName?: string;
};

function createRowKey<T extends Record<string, unknown>>(item: T, rowIndex: number): string {
  const maybeId = item.id;
  if (typeof maybeId === 'string' && maybeId.trim().length > 0) {
    return maybeId;
  }
  return `${rowIndex}-${JSON.stringify(item)}`;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  noDataMessage = 'No data available',
  maxHeight = 'max-h-[500px]',
  exportFileName = 'export',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [filters, setFilters] = useState<Record<string, string>>({});

  const autoFilterOptions = useMemo(() => {
    const optionsMap: Record<string, string[]> = {};
    columns.forEach((col) => {
      if (
        col.filterable === true &&
        col.filterType === 'select' &&
        col.filterOptions === undefined
      ) {
        const values = data
          .map((item) => {
            const value = item[col.key];
            return typeof value === 'string' && value.trim().length > 0 ? value : '';
          })
          .filter((value): value is string => value.length > 0);
        optionsMap[col.key] = Array.from(new Set(values));
      }
    });
    return optionsMap;
  }, [columns, data]);

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

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => {
      const next = { ...prev };
      if (value.trim().length === 0) {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  };

  const handleSortClick: React.MouseEventHandler<HTMLDivElement> = (event) => {
    const key = event.currentTarget.dataset.sortKey;
    if (typeof key === 'string') {
      handleSort(key);
    }
  };

  const processedData = useMemo(() => {
    let result = [...data];

    Object.entries(filters).forEach(([key, filterValue]) => {
      const col = columns.find((candidate) => candidate.key === key);
      const isSelect = col?.filterType === 'select';

      result = result.filter((item) => {
        const value = item[key];
        const val = String(value ?? '').toLowerCase();
        const fVal = filterValue.toLowerCase();
        if (isSelect) {
          return val === fVal;
        }
        return val.includes(fVal);
      });
    });

    if (sortKey !== null) {
      result.sort((a, b) => {
        const rawA = a[sortKey];
        const rawB = b[sortKey];
        const numA = typeof rawA === 'number' ? rawA : Number(rawA);
        const numB = typeof rawB === 'number' ? rawB : Number(rawB);

        let valA: string | number;
        let valB: string | number;
        if (Number.isFinite(numA) && Number.isFinite(numB)) {
          valA = numA;
          valB = numB;
        } else {
          valA = String(rawA ?? '').toLowerCase();
          valB = String(rawB ?? '').toLowerCase();
        }

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [columns, data, filters, sortDir, sortKey]);

  const handleExportCSV = () => {
    if (processedData.length === 0) return;

    const headers = columns.map((col) => `"${col.header.replace(/"/g, '""')}"`).join(',');

    const rows = processedData.map((item) => {
      return columns
        .map((col) => {
          let val = item[col.key];
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

      <div className={`w-full overflow-x-auto overflow-y-auto ${maxHeight}`}>
        <table className="w-full text-left border-collapse min-w-[600px]">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 text-xs font-bold text-gray-600 dark:text-gray-400 uppercase tracking-wider sticky top-0 z-10">
              {columns.map((col) => (
                <th key={col.key} className="p-4 select-none">
                  <div className="flex flex-col gap-2">
                    <div
                      className={`flex items-center gap-1.5 ${
                        col.sortable === true
                          ? 'cursor-pointer hover:text-gray-950 dark:hover:text-white'
                          : ''
                      }`}
                      data-sort-key={col.key}
                      onClick={col.sortable === true ? handleSortClick : undefined}
                    >
                      <span>{col.header}</span>
                      {col.sortable === true && (
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

                    {col.filterable === true && (
                      <div onClick={(event) => event.stopPropagation()}>
                        {col.filterType === 'select' ? (
                          <select
                            value={typeof filters[col.key] === 'string' ? filters[col.key] : ''}
                            onChange={(event) => handleFilterChange(col.key, event.target.value)}
                            className="w-full px-2 py-1 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded text-[11px] font-medium text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-600"
                          >
                            <option value="">All</option>
                            {(col.filterOptions ?? autoFilterOptions[col.key] ?? []).map(
                              (option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              )
                            )}
                          </select>
                        ) : (
                          <input
                            type="text"
                            placeholder="Filter..."
                            value={typeof filters[col.key] === 'string' ? filters[col.key] : ''}
                            onChange={(event) => handleFilterChange(col.key, event.target.value)}
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
                <td
                  colSpan={columns.length}
                  className="p-8 text-center text-gray-500 dark:text-gray-400"
                >
                  <div className="flex flex-col items-center justify-center gap-2">
                    <span className="font-semibold">{noDataMessage}</span>
                    <span className="text-xs opacity-75">
                      Try clearing filters or check back later
                    </span>
                  </div>
                </td>
              </tr>
            ) : (
              processedData.map((item, rowIndex) => (
                <tr
                  key={createRowKey(item, rowIndex)}
                  className="hover:bg-gray-50/50 dark:hover:bg-gray-900/20 text-gray-700 dark:text-gray-300 transition"
                >
                  {columns.map((col) => {
                    const value = item[col.key];
                    return (
                      <td key={col.key} className="p-4 align-middle">
                        <div
                          className={`truncate ${col.maxWidth ?? 'max-w-[200px]'}`}
                          title={
                            typeof value === 'object' && value !== null ? '' : String(value ?? '')
                          }
                        >
                          {col.render !== undefined ? col.render(value, item) : String(value ?? '')}
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
