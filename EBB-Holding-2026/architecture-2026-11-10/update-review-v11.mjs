import fs from 'node:fs';
const file = new URL('./build-review.mjs', import.meta.url);
let s = fs.readFileSync(file, 'utf8');
s = s.replaceAll('v1.0', 'v1.1');
s = s.replace('Точки признания долга и юридическая структура холдинга требуют подтверждения.', 'Долг поставщику — при подтверждении заказа. Типы денежных операций и статьи разделены. Юридическая структура холдинга ещё уточняется.');
s = s.replace("length,30);", "length,40);");
s = s.replace('acceptanceScenarios:30', 'acceptanceScenarios:40');
fs.writeFileSync(file,s);
