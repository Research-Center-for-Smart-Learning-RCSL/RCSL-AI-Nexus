import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import AuthLayout from '@/app/(auth)/layout';

describe('the authentication layout', () => {
  it('makes the complete brand a route back to the public home page', () => {
    render(<AuthLayout>Authentication screen</AuthLayout>);

    const home = screen.getByRole('link', { name: 'RCSL AI Nexus, home' });
    expect(home).toHaveAttribute('href', '/');
    expect(home).toHaveTextContent('RCSL AI Nexus');
    expect(home).toHaveTextContent('Management');
  });
});
