-- UTC scheduler: first delivery JST 07:30, then retry every 20 minutes to 09:50.
-- Daily device claims still prevent repeated delivery. No keys or user data here.
begin;
do $$
declare target_job bigint;
begin
 select jobid into strict target_job from cron.job where jobname='teilog-favorite-morning';
 perform cron.alter_job(target_job,schedule:='30,50 22 * * *');
 perform cron.schedule('teilog-favorite-morning-retry','10,30,50 23,0 * * *',
  $job$select teilog_private.queue_push('morning');$job$);
end $$;
commit;
