import React from 'react';

interface Props {
  name: string;
  items: string[];
}

export function Greeting({ name, items }: Props) {
  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold">Hello, {name}</h1>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {name && <span>has-name</span>}
    </div>
  );
}
