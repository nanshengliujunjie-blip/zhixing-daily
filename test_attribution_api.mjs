import assert from 'node:assert/strict';
import {matchesReport} from './fetch_attribution_api.mjs';

const row = {app_id:135, start_time:'2026-10-26 00:00:00', end_time:'2026-10-26 23:59:59',
  query_type:'1,2', remark:'daily:2026-10-26:test'};
assert(matchesReport(row, '2026-10-26', row.remark));
for (const change of [
  {app_id:136}, {start_time:'2026-10-25 00:00:00'}, {end_time:'2026-10-27 11:00:00'},
  {query_type:'1'}, {remark:'another-concurrent-request'},
]) assert.equal(matchesReport({...row, ...change}, '2026-10-26', row.remark), false);
assert.equal(matchesReport(row, '2026-10-25', row.remark), false);
console.log('PASS: report matching rejects other dates, products, types and concurrent tasks');
