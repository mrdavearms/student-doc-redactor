import React from 'react';
import ErrorFallback from './ErrorFallback';
import { useStore } from '../store';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Render error:', error, info);
    window.electronAPI?.logError?.({
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack ?? undefined,
      timestamp: new Date().toISOString(),
    });
  }

  handleReset = () => {
    useStore.getState().reset();
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return <ErrorFallback error={this.state.error} onReset={this.handleReset} />;
    }
    return this.props.children;
  }
}
