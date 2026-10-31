// 화면 하나가 그리다 멈춰도 앱 전체가 백지가 되지 않게 — 그 화면 자리에 까닭과 다시 그리기를 보이고, 주소가 바뀌면 처음부터 다시 그린다.
import { Component } from "react";
import type { ReactNode } from "react";
import { Banner, Button } from "../ui/primitives";

type Props = {
  children: ReactNode;
  /** 이 값이 바뀌면(다른 주소로 옮기면) 멈춘 표지를 걷고 다시 그린다. */
  resetKey: string;
};

type State = { error: Error | null; key: string };

/**
 * 렌더 중 던진 오류를 받는 경계. 서버 꼴이 타입과 다른 행 하나(예 칸이 빠진 쟁점 행의 `raisers_added.length`)가 #root 를 통째로 내려
 * 사이드바까지 사라지던 일을 그 화면 자리로 가둔다. 오류 글은 글자로만 보인다(HTML 로 해석하지 않는다).
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    // 주소가 바뀌면 앞 화면의 멈춤을 들고 가지 않는다.
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Banner
        title="이 화면을 그리다 멈췄습니다."
        detail={`${this.state.error.message} — 다시 그리거나 다른 화면으로 옮겨 가세요. 되풀이되면 이 글을 알려 주세요.`}
      >
        <Button type="button" variant="outline" size="sm" onClick={() => this.setState({ error: null })}>
          다시 그리기
        </Button>
      </Banner>
    );
  }
}
