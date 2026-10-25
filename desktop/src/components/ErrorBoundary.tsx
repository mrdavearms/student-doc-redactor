import React from 'react';
import ErrorFallback from './ErrorFallback';
import { useStore } from '../store';
import { errorLogPayload } from '../lib/faultReport';

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
    window.electronAPI?.logError?.(errorLogPayload(error, info.componentStack));
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
