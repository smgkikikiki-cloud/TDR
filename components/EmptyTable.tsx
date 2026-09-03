type Column = { label: string; width?: string };

export function EmptyTable({ columns, rows = 5 }: { columns: Column[]; rows?: number }) {
  return (
    <div className="tableShell">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c.label} style={{ width: c.width }}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, index) => (
            <tr key={index}>
              {columns.map((c, colIndex) => (
                <td key={c.label}>{colIndex === 0 ? <span className="placeholderText">รอใส่ข้อมูล</span> : <span className="dash">—</span>}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
