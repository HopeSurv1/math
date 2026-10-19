// 學生的「我的學習紀錄」頁：讀自己的學習紀錄畫出來（見 learning_report.js），可以按按鈕請 AI 寫學習建議。
// 沒登入（或登入失效）就回到首頁登入。
document.addEventListener('DOMContentLoaded', async () => {
    const container = document.getElementById('learningReport');
    const subtitle = document.getElementById('learningSubtitle');

    async function requestAdvice() {
        let res;
        try {
            res = await fetch('/api/learning/advice', { method: 'POST' });
        } catch (err) {
            throw new Error('網路好像怪怪的，請再試一次');
        }
        if (res.status === 401) {
            window.location.href = '/';
            throw new Error('請先登入');
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '產生失敗，請再試一次');
        return data.advice;
    }

    try {
        const res = await fetch('/api/learning/report');
        if (res.status === 401) {
            window.location.href = '/';
            return;
        }
        const report = await res.json();
        subtitle.textContent = `${report.username}，這裡整理了你和數學小老師的學習情形：常問哪些單元、哪裡需要加強。`;
        LearningReport.render(container, report, {
            conversationLink: (id) => `/?c=${encodeURIComponent(id)}`,
            requestAdvice,
            emptyText: '還沒有學習紀錄，先回去問老師幾個數學問題吧！',
        });
    } catch (err) {
        console.error('讀取學習紀錄失敗:', err);
        subtitle.textContent = '讀取學習紀錄失敗，請重新整理頁面再試一次。';
    }
});
