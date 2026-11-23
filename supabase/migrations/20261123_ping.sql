-- Keep-alive: evita pause do projeto free por inatividade.
create or replace function public.ping() returns int language sql stable set search_path = '' as 'select 1';
revoke all on function public.ping() from public;
grant execute on function public.ping() to anon, authenticated;
