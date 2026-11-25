import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api } from '../services/api';

type Review = {
  id: string;
  stars: number;
  comment: string | null;
  reply: string | null;
  user_name: string;
};

function ReplyForm({ id, account }: { id: string; account: string }) {
  const client = useQueryClient();
  const [reply, setReply] = useState('');
  const mutation = useMutation({
    mutationFn: () => api.post(`/ratings/${id}/reply`, { reply: reply.trim() }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['seller-reviews', account] }),
  });
  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      <label className="grid gap-1 text-sm">
        Your reply
        <textarea
          className="rounded border bg-transparent p-2"
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          maxLength={1000}
          required
        />
      </label>
      <button
        className="rounded border px-3 py-1"
        type="submit"
        disabled={mutation.isPending || mutation.isSuccess || reply.trim().length === 0}
      >
        Post reply
      </button>
      {mutation.isError && (
        <p role="alert">Reply could not be saved. Refresh to check for an existing reply.</p>
      )}
    </form>
  );
}

export function SellerReviews({ account }: { account: string }) {
  const reviews = useQuery({
    queryKey: ['seller-reviews', account],
    queryFn: async ({ signal }): Promise<Review[]> =>
      (await api.get<Review[]>('/ratings/seller', { signal })).data,
  });
  return (
    <section className="glass-card space-y-3 p-4">
      <h2 className="text-lg font-semibold">Customer reviews</h2>
      {reviews.isPending && <p role="status">Loading reviews…</p>}
      {reviews.isError && <p role="alert">Reviews are unavailable.</p>}
      {reviews.data?.length === 0 && <p>No reviews yet.</p>}
      {reviews.data?.map((review) => (
        <article className="space-y-2 border-t py-3" key={review.id}>
          <h3 className="font-semibold">
            {review.user_name} · {review.stars}/5
          </h3>
          <p>{review.comment}</p>
          {review.reply === null ? (
            <ReplyForm account={account} id={review.id} />
          ) : (
            <p>Seller reply: {review.reply}</p>
          )}
        </article>
      ))}
    </section>
  );
}
