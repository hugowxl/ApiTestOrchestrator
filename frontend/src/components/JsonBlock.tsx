export function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="json-block mono">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
