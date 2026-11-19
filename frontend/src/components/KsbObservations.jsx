import React from 'react';

export default function KsbObservations({ columns, checkpoints, readings, onChange, sampleLabel = 'Sample', methodLabel = 'Method of inspection' }) {
  const fieldStyle = 'w-full min-w-20 rounded border px-2 py-1 text-xs focus:ring-1 focus:ring-blue-600';
  return (
    <div className="max-h-[550px] overflow-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead className="sticky top-0 bg-gray-800 text-white">
          <tr>
            <th rowSpan={2} className="border px-2">Sr. No.</th>
            <th rowSpan={2} className="min-w-44 border px-2">Parameter description</th>
            <th rowSpan={2} className="min-w-36 border px-2">Specification</th>
            <th rowSpan={2} className="min-w-28 border px-2">{methodLabel}</th>
            <th colSpan={columns.length} className="border p-2 text-center">Observation by pump serial number</th>
            <th rowSpan={2} className="border px-2">Remarks</th>
          </tr>
          <tr>
            {columns.map((column, index) => (
              <th key={column} className="border p-1">
                <input
                  aria-label={`Pump serial number ${index + 1}`}
                  placeholder={`${sampleLabel} ${index + 1}`}
                  value={readings[16]?.[column] || ''}
                  onChange={event => onChange(16, column, event.target.value)}
                  className={`${fieldStyle} bg-white font-normal text-gray-900`}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {checkpoints.map(check => (
            <tr key={check.row_index} className="align-top">
              {[check.item_sn, check.parameter, check.specification, check.method].map((value, index) => (
                <td key={index} className="whitespace-pre-line border px-2 py-1.5">{value}</td>
              ))}
              {[...columns, 'U'].map((column, index) => (
                <td key={column} className="border p-1">
                  <input
                    aria-label={`Checkpoint ${check.item_sn} ${column === 'U' ? 'remarks' : `sample ${index + 1}`}`}
                    value={readings[check.row_index]?.[column] || ''}
                    onChange={event => onChange(check.row_index, column, event.target.value)}
                    className={fieldStyle}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
