import type { Product } from '../services/api';

export const emptyFacts = {
  brand: '',
  package: '',
  cost: '',
  ingredients: '',
  dietary: '',
  allergens: '',
  nutrition: '',
  source: '',
};
export type GroceryFacts = typeof emptyFacts;

export function formFacts(product: Product): GroceryFacts {
  return {
    brand: product.brand ?? '',
    package: product.package ?? '',
    cost: String(product.cost_price ?? ''),
    ingredients: product.ingredients ?? '',
    dietary: product.dietary_tags?.join(', ') ?? '',
    allergens:
      product.allergens === undefined || product.allergens === null
        ? ''
        : product.allergens.join(', ') || 'none listed',
    nutrition: Object.entries(product.nutrition ?? {})
      .map(([label, value]) => `${label}=${value}`)
      .join('\n'),
    source: product.label_source ?? '',
  };
}

export function productFacts(fields: GroceryFacts) {
  const split = (value: string) =>
    value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean);
  const nutrition = Object.fromEntries(
    fields.nutrition
      .split('\n')
      .filter((line) => line.includes('='))
      .map((line) => {
        const index = line.indexOf('=');
        return [line.slice(0, index).trim(), line.slice(index + 1).trim()];
      })
  );
  return {
    brand: fields.brand.trim(),
    package: fields.package.trim(),
    cost_price: fields.cost,
    ingredients: fields.ingredients.trim() || null,
    dietary_tags: fields.dietary.trim().length === 0 ? null : split(fields.dietary),
    allergens:
      fields.allergens.trim().toLowerCase() === 'none listed'
        ? []
        : fields.allergens.trim().length === 0
          ? null
          : split(fields.allergens),
    nutrition: Object.keys(nutrition).length === 0 ? null : nutrition,
    label_source: fields.source.trim() || null,
  };
}

export function GroceryFactsFields({
  values,
  onChange,
}: {
  values: GroceryFacts;
  onChange: (fields: GroceryFacts) => void;
}) {
  return (
    <fieldset className="space-y-2 rounded-xl border p-3">
      <legend className="px-1 font-medium">Package and label details</legend>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(
          [
            ['brand', 'Brand', 'text', false],
            ['package', 'Package size', 'text', true],
            ['cost', 'Cost per package (₹)', 'number', true],
            ['ingredients', 'Ingredients', 'text', false],
            ['dietary', 'Dietary labels, separated by commas', 'text', false],
            ['allergens', 'Listed allergens, or “none listed”', 'text', false],
            ['source', 'Label source', 'text', false],
          ] as const
        ).map(([key, name, type, required]) => (
          <label key={key} className="grid gap-1 text-xs">
            {name}
            <input
              className="rounded-lg border bg-transparent p-2"
              type={type}
              value={values[key]}
              required={required}
              min={type === 'number' ? 0 : undefined}
              step={type === 'number' ? '0.01' : undefined}
              onChange={(event) => onChange({ ...values, [key]: event.target.value })}
            />
          </label>
        ))}
      </div>
      <label className="grid gap-1 text-xs">
        Nutrition. Enter one field per line, such as Protein=3.2 g per 100 ml
        <textarea
          className="rounded-lg border bg-transparent p-2"
          value={values.nutrition}
          onChange={(event) => onChange({ ...values, nutrition: event.target.value })}
        />
      </label>
      {values.ingredients.trim().length === 0 ||
      values.allergens.trim().length === 0 ||
      values.source.trim().length === 0 ? (
        <p className="text-xs text-amber-800 dark:text-amber-300">
          Missing label details can reduce search visibility. Shoppers will see missing allergen
          information as unknown.
        </p>
      ) : null}
    </fieldset>
  );
}
