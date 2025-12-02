"use client";

import { useState, useEffect, FormEvent } from 'react';

interface Plan {
  _id: string;
  name: string;
  price: number;
}

export default function AdminPlansPage() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<string>('');
  const [newPrice, setNewPrice] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const API_BASE_URL = 'http://localhost:5000';

  const fetchPlans = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/plans`);
      if (!response.ok) {
        throw new Error('Failed to fetch plans');
      }
      const data: Plan[] = await response.json();
      setPlans(data);
      if (data.length > 0) {
        setSelectedPlan(data[0].name);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPlans();
  }, []);

  const handleUpdatePrice = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedPlan || newPrice === '') {
      setError('Please select a plan and enter a new price.');
      return;
    }

    setIsUpdating(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await fetch(`${API_BASE_URL}/update-plan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: selectedPlan,
          new_price: parseFloat(newPrice),
        }),
      });

      const result = await response.json();

      if (!response.ok || !result.success) {
        throw new Error(result.message || 'Failed to update price');
      }

      setSuccess(`Successfully updated ${selectedPlan} to €${newPrice}`);
      setNewPrice('');
      // Re-fetch plans to show the updated price
      await fetchPlans(); 
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsUpdating(false);
      // Toast notification for success
      if (success) {
          setTimeout(() => setSuccess(null), 3000);
      }
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-100 font-sans">
      <main className="w-full max-w-lg rounded-xl bg-white p-8 shadow-2xl">
        <h1 className="mb-8 text-center text-4xl font-bold text-gray-800">
          Admin Plan Price Dashboard
        </h1>

        {success && (
          <div className="mb-4 rounded-md bg-green-100 p-4 text-center text-green-700">
            {success}
          </div>
        )}
        
        <div className="mb-8">
          <h2 className="mb-4 text-2xl font-semibold text-gray-700">
            Current Prices
          </h2>
          {isLoading ? (
            <p className="text-gray-500">Loading prices...</p>
          ) : error ? (
            <p className="text-red-500">{error}</p>
          ) : (
            <ul className="space-y-3">
              {plans.map((plan) => (
                <li
                  key={plan._id}
                  className="flex items-center justify-between rounded-lg bg-gray-50 p-4"
                >
                  <span className="text-lg font-medium text-gray-600">{plan.name}</span>
                  <span className="text-xl font-bold text-gray-900">€{plan.price.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h2 className="mb-4 text-2xl font-semibold text-gray-700">
            Update a Plan
          </h2>
          <form onSubmit={handleUpdatePrice} className="space-y-6">
            <div>
              <label htmlFor="plan-select" className="mb-2 block font-medium text-gray-600">
                Select Plan
              </label>
              <select
                id="plan-select"
                value={selectedPlan}
                onChange={(e) => setSelectedPlan(e.target.value)}
                className="w-full rounded-lg border border-gray-300 p-3 text-lg focus:border-indigo-500 focus:ring-indigo-500"
                disabled={isLoading || plans.length === 0}
              >
                {plans.map((plan) => (
                  <option key={plan._id} value={plan.name}>
                    {plan.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="new-price" className="mb-2 block font-medium text-gray-600">
                New Price (€)
              </label>
              <input
                id="new-price"
                type="number"
                step="0.01"
                min="0"
                value={newPrice}
                onChange={(e) => setNewPrice(e.target.value)}
                className="w-full rounded-lg border border-gray-300 p-3 text-lg focus:border-indigo-500 focus:ring-indigo-500"
                placeholder="e.g., 25.00"
                disabled={isUpdating}
              />
            </div>

            <button
              type="submit"
              className="w-full rounded-full bg-indigo-600 px-6 py-3 text-lg font-semibold text-white shadow-md transition-transform duration-150 hover:scale-105 hover:bg-indigo-700 disabled:bg-gray-400"
              disabled={isUpdating}
            >
              {isUpdating ? 'Updating...' : 'Update Price'}
            </button>
          </form>
          {error && <p className="mt-4 text-center text-red-600">{error}</p>}
        </div>
      </main>
    </div>
  );
}
